"""
WhatsApp Media Organizer - Database Decryption Engine.
Handles 64-character hex key derivation and wadecrypt execution.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def validate_hex_key(hex_key):
    """
    Validates that a given string is a valid 64-character hexadecimal key.
    Returns (is_valid: bool, error_message: str).
    """
    if not hex_key or not isinstance(hex_key, str):
        return False, "Key cannot be empty."
    cleaned = hex_key.strip().replace(" ", "").replace("-", "")
    if len(cleaned) != 64:
        return False, f"Expected 64 hexadecimal characters, but received {len(cleaned)}."
    try:
        bytes.fromhex(cleaned)
        return True, ""
    except ValueError:
        return False, "Key contains non-hexadecimal characters. Allowed characters are 0-9 and a-f."


def create_key_file(hex_key, outpath="encrypted_backup.key"):
    """
    Generates a 59-byte Key15 binary file from a 64-character hexadecimal key.
    Returns the resolved output file path.
    """
    is_valid, err = validate_hex_key(hex_key)
    if not is_valid:
        raise ValueError(f"Invalid encryption key: {err}")

    cleaned = hex_key.strip().replace(" ", "").replace("-", "")
    try:
        from wa_crypt_tools.lib.key.key15 import Key15
    except ImportError:
        raise RuntimeError(
            "wa-crypt-tools is not installed in the current environment. "
            "Please run: pip install wa-crypt-tools"
        )

    key = Key15(keyarray=bytes.fromhex(cleaned))
    out_file = Path(outpath).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with open(out_file, "wb") as f:
        f.write(key.dump())

    return str(out_file)


def find_wadecrypt_binary():
    """
    Locates the wadecrypt executable in standard virtual environment and system paths.
    Returns the resolved absolute path or 'wadecrypt' if on system PATH.
    """
    script_dir = Path(__file__).resolve().parent.parent
    py_dir = Path(sys.executable).parent

    candidates = [
        py_dir / "wadecrypt.exe",
        py_dir / "wadecrypt",
        py_dir / "Scripts" / "wadecrypt.exe",
        script_dir / "venv" / "Scripts" / "wadecrypt.exe",
        script_dir / "venv" / "bin" / "wadecrypt",
        script_dir / ".venv" / "Scripts" / "wadecrypt.exe",
        script_dir / ".venv" / "bin" / "wadecrypt",
        script_dir / "wadecrypt.exe",
        script_dir / "wadecrypt",
    ]

    for cand in candidates:
        if cand.is_file():
            return str(cand)

    # Check if wadecrypt is on system PATH
    found = shutil.which("wadecrypt")
    if found:
        return found

    return "wadecrypt"


def decrypt_db_stream(key_file, crypt_path, out_path, cancellation_token=None, progress_callback=None):
    """
    High-speed, zero-RAM streaming decryption for WhatsApp crypt15 databases.
    Decrypts and decompresses in 2 MB chunks directly to disk.
    Memory usage is strictly bounded under 20 MB regardless of database size.
    Returns True if successful, False if cancelled or unsupported.
    """
    import zlib
    from Cryptodome.Cipher import AES
    from wa_crypt_tools.lib.key.keyfactory import KeyFactory
    from wa_crypt_tools.lib.db.dbfactory import DatabaseFactory

    key_p = Path(key_file).resolve()
    crypt_p = Path(crypt_path).resolve()
    out_p = Path(out_path).resolve()

    key = KeyFactory.new(str(key_p))
    out_p.parent.mkdir(parents=True, exist_ok=True)
    temp_out_p = out_p.with_name(f"{out_p.name}.tmp_decrypt")

    try:
        with open(crypt_p, "rb") as f_in, open(temp_out_p, "wb") as f_out:
            db = DatabaseFactory.from_file(f_in)
            if str(db) != "Database15":
                # Only Crypt15 supports this exact GCM streaming format
                return False

            cipher = AES.new(key.get(), AES.MODE_GCM, db.get_iv())
            z_obj = zlib.decompressobj()

            total_size = crypt_p.stat().st_size
            total_payload = total_size - f_in.tell() - 32
            if total_payload <= 0:
                return False

            bytes_read = 0
            chunk_size = 2 * 1024 * 1024  # 2 MB optimal streaming buffer

            while bytes_read < total_payload:
                if cancellation_token and cancellation_token.is_set():
                    return False

                to_read = min(chunk_size, total_payload - bytes_read)
                chunk = f_in.read(to_read)
                if not chunk:
                    break
                bytes_read += len(chunk)

                dec_chunk = cipher.decrypt(chunk)
                decomp_chunk = z_obj.decompress(dec_chunk)
                if decomp_chunk:
                    f_out.write(decomp_chunk)

                if progress_callback:
                    try:
                        progress_callback(bytes_read, total_payload)
                    except Exception:
                        pass

            # Read the 32-byte footer (authentication tag + checksum)
            footer = f_in.read(32)
            if len(footer) >= 16:
                auth_tag = footer[:16]
                try:
                    cipher.verify(auth_tag)
                except Exception as e_tag:
                    sys.stderr.write(f"[Decrypt] Warning: Auth tag mismatch (continuing): {e_tag}\n")

        # Atomic replacement of output database
        if temp_out_p.is_file() and temp_out_p.stat().st_size >= 16:
            # Validate SQLite magic header before accepting decrypted stream
            try:
                with open(temp_out_p, "rb") as f_chk:
                    magic = f_chk.read(16)
                if magic != b"SQLite format 3\x00":
                    sys.stderr.write(f"[Decrypt] Stream decryption produced invalid header: {magic!r}\n")
                    try:
                        temp_out_p.unlink()
                    except Exception:
                        pass
                    return False
            except Exception as e_chk:
                sys.stderr.write(f"[Decrypt] Header check failed: {e_chk}\n")
                return False

            if out_p.is_file():
                try:
                    out_p.unlink()
                except Exception:
                    pass
            temp_out_p.replace(out_p)
            return True
        return False
    except Exception as e:
        sys.stderr.write(f"[Decrypt] Stream decryption note: {e}, falling back to wadecrypt\n")
        if temp_out_p.is_file():
            try:
                temp_out_p.unlink()
            except Exception:
                pass
        return False


def decrypt_db(key_file, crypt_path, out_path, cancellation_token=None, progress_callback=None):
    """
    Decrypts an encrypted msgstore database using streaming zero-RAM decryption
    with automatic fallback to wadecrypt for legacy formats (crypt12/14).
    Validates that the output file begins with the standard SQLite header.
    Raises RuntimeError if decryption fails or yields an invalid database.
    """
    key_p = Path(key_file).resolve()
    crypt_p = Path(crypt_path).resolve()
    out_p = Path(out_path).resolve()

    if not key_p.is_file():
        raise FileNotFoundError(f"Key file not found: {key_file}")
    if not crypt_p.is_file():
        raise FileNotFoundError(f"Crypt file not found: {crypt_path}")

    out_p.parent.mkdir(parents=True, exist_ok=True)

    # 1. High-speed, zero-RAM streaming decryption (handles Crypt15)
    if crypt_p.name.endswith(".crypt15"):
        try:
            stream_success = decrypt_db_stream(
                key_p,
                crypt_p,
                out_p,
                cancellation_token=cancellation_token,
                progress_callback=progress_callback,
            )
            if stream_success and out_p.is_file() and out_p.stat().st_size >= 16:
                # Fast check that output is valid SQLite
                with open(out_p, "rb") as f_hdr:
                    if f_hdr.read(16) == b"SQLite format 3\x00":
                        return str(out_p)
                try:
                    out_p.unlink()
                except Exception:
                    pass
        except Exception as e_stream:
            sys.stderr.write(f"[Decrypt] Fast stream decryption skipped: {e_stream}\n")

    if cancellation_token and cancellation_token.is_set():
        return str(out_p)

    # 2. Standard wadecrypt fallback (invoked via python -m to avoid Windows wrapper bugs)
    cmd = [sys.executable, "-m", "wa_crypt_tools.wadecrypt", str(key_p), str(crypt_p), str(out_p)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "wadecrypt executable was not found. "
            "Ensure the virtual environment is activated and wa-crypt-tools is installed."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Decryption timed out after 300 seconds.")

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip() or "Unknown decryption error"
        raise RuntimeError(f"Decryption failed with code {proc.returncode}: {err_msg}")

    if not out_p.is_file() or out_p.stat().st_size == 0:
        raise RuntimeError(
            f"Decryption completed but output file '{out_path}' was not created or is empty."
        )

    # 3. Validate that decrypted output is actually a valid SQLite database
    try:
        with open(out_p, "rb") as f_val:
            magic = f_val.read(16)
    except Exception as e_read:
        raise RuntimeError(f"Failed to read decrypted file '{out_path}': {e_read}")

    if magic != b"SQLite format 3\x00":
        try:
            out_p.unlink()
        except Exception:
            pass

        if crypt_p.name.endswith((".crypt14", ".crypt12")):
            raise RuntimeError(
                f"Decryption failed: '{crypt_p.name}' is a legacy unencrypted backup (Crypt14/Crypt12). "
                "A 64-digit key only decrypts modern End-to-End Encrypted backups (Crypt15).\n\n"
                "Please wait for WhatsApp on your phone to finish backing up (100%), then resume sync. "
                "If backup has not started, open WhatsApp > Settings > Chats > Chat backup and tap 'Back up'."
            )
        elif crypt_p.name.endswith(".crypt15"):
            raise RuntimeError(
                f"Decryption failed for '{crypt_p.name}'. The 64-digit key provided does not match this backup, "
                "or the backup file was corrupted during transfer. Please verify your 64-digit key in Settings."
            )
        else:
            raise RuntimeError(
                f"Decryption failed: output is not a valid SQLite database (header: {magic!r})."
            )

    return str(out_p)

