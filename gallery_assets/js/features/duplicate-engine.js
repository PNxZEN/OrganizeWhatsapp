/* In-browser duplicate clustering engine
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Cache and compute duplicate clusters for a chat
function computeChatDuplicates(chat) {
    if (!chat) return { chatDupSet: new Set(), dupInfoMap: {}, duplicateGroups: [] };
    if (typeof isDuplicateDetectionEnabled === 'function' && !isDuplicateDetectionEnabled()) {
        return { chatDupSet: new Set(), dupInfoMap: {}, duplicateGroups: [] };
    }
    if (chat._dupCache) return chat._dupCache;

    const chatDupSet = new Set();
    const dupInfoMap = {};
    const rawList = chat.media || [];
    const seenRel = new Set();
    const mediaList = [];
    for (const item of rawList) {
        const r = item.rel_path;
        if (r) {
            if (seenRel.has(r)) continue;
            seenRel.add(r);
        }
        mediaList.push(item);
    }

    // Helper: Disjoint Set Union (DSU)
    const parent = Array.from({ length: mediaList.length }, (_, idx) => idx);
    function findRoot(i) {
        let root = i;
        while (root !== parent[root]) root = parent[root];
        let curr = i;
        while (curr !== root) {
            let nxt = parent[curr];
            parent[curr] = root;
            curr = nxt;
        }
        return root;
    }
    function unionNodes(i, j) {
        const ri = findRoot(i);
        const rj = findRoot(j);
        if (ri !== rj) parent[ri] = rj;
    }

    // Helper: Hamming distance between two hex pHash strings
    function hexHammingDist(h1, h2) {
        if (!h1 || !h2 || h1.length !== h2.length) return 999;
        let dist = 0;
        for (let k = 0; k < h1.length; k++) {
            let v = parseInt(h1[k], 16) ^ parseInt(h2[k], 16);
            while (v > 0) {
                dist += (v & 1);
                v >>= 1;
            }
        }
        return dist;
    }

    // 1. Link items using backend duplicate_primary if present
    const filenameToIndex = new Map();
    mediaList.forEach((item, idx) => {
        if (item.filename) {
            filenameToIndex.set(item.filename, idx);
        }
    });

    mediaList.forEach((item, idx) => {
        if (!isImageItem(item) && !isVideoItem(item)) return;
        if (item.is_duplicate && item.duplicate_primary) {
            const primaryIdx = filenameToIndex.get(item.duplicate_primary);
            if (primaryIdx !== undefined) {
                const primaryItem = mediaList[primaryIdx];
                if (primaryItem) {
                    const isImgA = isImageItem(item) && !isVideoItem(item);
                    const isImgB = isImageItem(primaryItem) && !isVideoItem(primaryItem);
                    const isVidA = isVideoItem(item);
                    const isVidB = isVideoItem(primaryItem);
                    if ((isImgA && isImgB) || (isVidA && isVidB)) {
                        unionNodes(idx, primaryIdx);
                    }
                }
            }
        }
    });

    // 2. Exact MD5 grouping (images and videos separately)
    const imgMd5Groups = new Map();
    const vidMd5Groups = new Map();
    mediaList.forEach((item, idx) => {
        if (!item.md5) return;
        if (isImageItem(item) && !isVideoItem(item)) {
            if (!imgMd5Groups.has(item.md5)) imgMd5Groups.set(item.md5, []);
            imgMd5Groups.get(item.md5).push(idx);
        } else if (isVideoItem(item)) {
            if (!vidMd5Groups.has(item.md5)) vidMd5Groups.set(item.md5, []);
            vidMd5Groups.get(item.md5).push(idx);
        }
    });
    imgMd5Groups.forEach(indices => {
        for (let k = 1; k < indices.length; k++) {
            unionNodes(indices[0], indices[k]);
        }
    });
    vidMd5Groups.forEach(indices => {
        for (let k = 1; k < indices.length; k++) {
            unionNodes(indices[0], indices[k]);
        }
    });

    // 3. Filename collision groups (_dup\d+) (images and videos separately)
    const imgStemGroups = new Map();
    const vidStemGroups = new Map();
    mediaList.forEach((item, idx) => {
        const fn = item.filename || '';
        const stem = fn.replace(/\.[^.]+$/, '').replace(/_dup\d+$/i, '').toLowerCase();
        const ext = (fn.match(/\.[^.]+$/) || [''])[0].toLowerCase();
        if (!stem) return;
        const key = `${stem}${ext}`;
        if (isImageItem(item) && !isVideoItem(item)) {
            if (!imgStemGroups.has(key)) imgStemGroups.set(key, []);
            imgStemGroups.get(key).push(idx);
        } else if (isVideoItem(item)) {
            if (!vidStemGroups.has(key)) vidStemGroups.set(key, []);
            vidStemGroups.get(key).push(idx);
        }
    });
    imgStemGroups.forEach(indices => {
        if (indices.length > 1) {
            for (let k = 1; k < indices.length; k++) {
                unionNodes(indices[0], indices[k]);
            }
        }
    });
    vidStemGroups.forEach(indices => {
        if (indices.length > 1) {
            for (let k = 1; k < indices.length; k++) {
                unionNodes(indices[0], indices[k]);
            }
        }
    });

    function isValidDuplicateCandidate(itemA, itemB) {
        if (!itemA || !itemB) return false;
        const isImgA = isImageItem(itemA) && !isVideoItem(itemA);
        const isImgB = isImageItem(itemB) && !isVideoItem(itemB);
        const isVidA = isVideoItem(itemA);
        const isVidB = isVideoItem(itemB);

        // Reject cross-media (image with video) or non-media
        if (!((isImgA && isImgB) || (isVidA && isVidB))) return false;

        const keyA = itemA.rel_path || itemA.filename;
        const keyB = itemB.rel_path || itemB.filename;
        if (window._ignoredDupKeys && (window._ignoredDupKeys.has(keyA) || window._ignoredDupKeys.has(keyB) || window._ignoredDupKeys.has(itemA.filename) || window._ignoredDupKeys.has(itemB.filename))) {
            return false;
        }
        // Byte-identical copies are always duplicates
        if (itemA.md5 && itemB.md5 && itemA.md5 === itemB.md5) {
            return true;
        }
        // Explicit collision names (_dup1) are duplicates
        const fnA = itemA.filename || '';
        const fnB = itemB.filename || '';
        const stemA = fnA.replace(/\.[^.]+$/, '').replace(/_dup\d+$/i, '').toLowerCase();
        const stemB = fnB.replace(/\.[^.]+$/, '').replace(/_dup\d+$/i, '').toLowerCase();
        if (stemA === stemB && (/_dup\d+/i.test(fnA) || /_dup\d+/i.test(fnB))) {
            return true;
        }

        if (isVidA && isVidB) {
            // Duration tolerance guard: true duplicates must have matching duration (<= 0.5s)
            const durA = itemA.media_duration !== undefined ? itemA.media_duration : (window._cachedImageDims[keyA]?.dur);
            const durB = itemB.media_duration !== undefined ? itemB.media_duration : (window._cachedImageDims[keyB]?.dur);
            if (durA !== undefined && durB !== undefined && durA !== null && durB !== null) {
                if (Math.abs(Number(durA) - Number(durB)) > 0.5) return false;
            }

            // If frame hashes are available, compare them:
            const vHashA = window._cachedVideo3FrameHashes?.[keyA];
            const vHashB = window._cachedVideo3FrameHashes?.[keyB];
            if (vHashA && vHashB) {
                return compareVideo3FrameHashes(vHashA, vHashB);
            }

            // If neither exact MD5 nor collision stem, and frame hashes are unavailable,
            // do not blindly consider them a quality duplicate unless explicitly marked by backend
            if (itemA.duplicate_primary === itemB.filename || itemB.duplicate_primary === itemA.filename) {
                return true;
            }
            return false;
        }

        // Layered guards for images:
        // Guard 1: Aspect Ratio Invariance (strict 2% tolerance when dimensions are known)
        const wA = itemA.width || 0, heightA = itemA.height || 0;
        const wB = itemB.width || 0, heightB = itemB.height || 0;
        if (wA > 0 && heightA > 0 && wB > 0 && heightB > 0) {
            const rA = wA / heightA;
            const rB = wB / heightB;
            if (Math.abs(rA - rB) > 0.02) {
                return false;
            }
        }

        // Guard 2: If both images have max dimension > 1600 px, neither is an SD copy!
        const maxDimA = Math.max(wA, heightA);
        const maxDimB = Math.max(wB, heightB);
        if (maxDimA > 1600 && maxDimB > 1600) {
            return false;
        }

        // Guard 3: File size ratio (true WhatsApp quality compression achieves >= 1.35x reduction)
        // Burst shots typically have 1.00x - 1.15x ratio
        const szA = itemA.size_bytes || 0;
        const szB = itemB.size_bytes || 0;
        if (szA > 0 && szB > 0) {
            const ratio = Math.max(szA, szB) / Math.min(szA, szB);
            const hasDimStepdown = (maxDimA > 1600 && maxDimB <= 1600) || (maxDimB > 1600 && maxDimA <= 1600);
            if (ratio < 1.35 && !hasDimStepdown) {
                return false;
            }
        }
        return true;
    }

    // 4. Perceptual pHash clustering (images only): strict threshold dist <= 2
    // Uses Pigeonhole Multi-Index Hashing:
    // 16-hex char pHash is partitioned into 4 blocks of 4 hex chars (16 bits each).
    // Any two hashes with Hamming distance <= 2 must have 0 bit errors in at least 2 blocks.
    // Indexing into 4 block tables eliminates the O(N^2) multi-million iteration loop down to O(1) candidate lookup,
    // preventing JavaScript event loop freezes on large chats.
    const blockTables = [new Map(), new Map(), new Map(), new Map()];
    const phashItems = [];
    mediaList.forEach((item, idx) => {
        if (!isImageItem(item) || isVideoItem(item)) return;
        const ph = item.phash;
        if (ph && ph.length >= 16) {
            phashItems.push({ idx, phash: ph, item });
            const pIdx = phashItems.length - 1;
            for (let b = 0; b < 4; b++) {
                const chunk = ph.substr(b * 4, 4);
                let bucket = blockTables[b].get(chunk);
                if (!bucket) {
                    bucket = [];
                    blockTables[b].set(chunk, bucket);
                }
                bucket.push(pIdx);
            }
        }
    });

    const checkedPairs = new Set();
    for (let b = 0; b < 4; b++) {
        blockTables[b].forEach(indices => {
            if (indices.length > 1) {
                for (let i = 0; i < indices.length; i++) {
                    const pA = indices[i];
                    const candA = phashItems[pA];
                    const rootA = findRoot(candA.idx);
                    for (let j = i + 1; j < indices.length; j++) {
                        const pB = indices[j];
                        const candB = phashItems[pB];
                        if (rootA === findRoot(candB.idx)) continue;

                        const minIdx = pA < pB ? pA : pB;
                        const maxIdx = pA < pB ? pB : pA;
                        const pairKey = (minIdx * 100000) + maxIdx;
                        if (checkedPairs.has(pairKey)) continue;
                        checkedPairs.add(pairKey);

                        if (hexHammingDist(candA.phash, candB.phash) <= 2) {
                            if (isValidDuplicateCandidate(candA.item, candB.item)) {
                                unionNodes(candA.idx, candB.idx);
                            }
                        }
                    }
                }
            }
        });
    }

    // 5a. WhatsApp quality pairs: images (IMG-YYYYMMDD-WAXXXX)
    const waImgPattern = /^IMG-(\d{8})-WA(\d{4})(?:_dup\d+)?(?:\.[^.]+)?$/i;
    const waImgBuckets = new Map();
    mediaList.forEach((item, idx) => {
        if (!isImageItem(item) || isVideoItem(item)) return;
        const fn = item.filename || '';
        const m = fn.match(waImgPattern);
        if (m) {
            const dateStr = m[1];
            const counter = parseInt(m[2], 10);
            const bucketKey = `IMG_${dateStr}`;
            if (!waImgBuckets.has(bucketKey)) waImgBuckets.set(bucketKey, []);
            waImgBuckets.get(bucketKey).push({ idx, counter, item });
        }
    });

    waImgBuckets.forEach(bucket => {
        if (bucket.length > 1) {
            bucket.sort((a, b) => a.counter - b.counter);
            for (let a = 0; a < bucket.length; a++) {
                for (let b = a + 1; b < bucket.length; b++) {
                    const diff = Math.abs(bucket[a].counter - bucket[b].counter);
                    if (diff > 4) break;
                    const itemA = bucket[a].item;
                    const itemB = bucket[b].item;
                    if (findRoot(bucket[a].idx) === findRoot(bucket[b].idx)) continue;
                    if (!isValidDuplicateCandidate(itemA, itemB)) continue;
                    let isPair = false;
                    if (itemA.phash && itemB.phash) {
                        if (hexHammingDist(itemA.phash, itemB.phash) <= 2) {
                            isPair = true;
                        }
                    }
                    if (isPair) {
                        unionNodes(bucket[a].idx, bucket[b].idx);
                    }
                }
            }
        }
    });

    // 5b. WhatsApp quality pairs: videos (VID-YYYYMMDD-WAXXXX.mp4)
    const waVidPattern = /^VID-(\d{8})-WA(\d{4})(?:_dup\d+)?(?:\.[^.]+)?$/i;
    const waVidBuckets = new Map();
    mediaList.forEach((item, idx) => {
        if (!isVideoItem(item)) return;
        const fn = item.filename || '';
        const m = fn.match(waVidPattern);
        if (m) {
            const dateStr = m[1];
            const counter = parseInt(m[2], 10);
            const bucketKey = `VID_${dateStr}`;
            if (!waVidBuckets.has(bucketKey)) waVidBuckets.set(bucketKey, []);
            waVidBuckets.get(bucketKey).push({ idx, counter, item });
        }
    });

    waVidBuckets.forEach(bucket => {
        if (bucket.length > 1) {
            bucket.sort((a, b) => a.counter - b.counter);
            for (let a = 0; a < bucket.length; a++) {
                for (let b = a + 1; b < bucket.length; b++) {
                    const diff = Math.abs(bucket[a].counter - bucket[b].counter);
                    if (diff > 4) break;
                    const itemA = bucket[a].item;
                    const itemB = bucket[b].item;
                    if (findRoot(bucket[a].idx) === findRoot(bucket[b].idx)) continue;
                    if (!isValidDuplicateCandidate(itemA, itemB)) continue;

                    const keyA = itemA.rel_path || itemA.filename;
                    const keyB = itemB.rel_path || itemB.filename;
                    const hA = window._cachedVideo3FrameHashes?.[keyA];
                    const hB = window._cachedVideo3FrameHashes?.[keyB];

                    let isPair = false;
                    if (hA && hB) {
                        if (compareVideo3FrameHashes(hA, hB)) {
                            isPair = true;
                        }
                    }
                    if (isPair) {
                        unionNodes(bucket[a].idx, bucket[b].idx);
                    }
                }
            }
        }
    });

    // 6. Assemble clusters, rank to select PRIMARY KEEPER, and mark duplicates
    const clusterMap = new Map();
    mediaList.forEach((item, idx) => {
        const root = findRoot(idx);
        if (!clusterMap.has(root)) clusterMap.set(root, []);
        clusterMap.get(root).push(item);
    });

    const primarySet = new Set();
    clusterMap.forEach(cluster => {
        if (cluster.length > 1) {
            cluster.sort((a, b) => {
                const isManA = (window._manualSwappedPrimaries && (window._manualSwappedPrimaries.has(a.rel_path) || window._manualSwappedPrimaries.has(a.filename))) ? 1 : 0;
                const isManB = (window._manualSwappedPrimaries && (window._manualSwappedPrimaries.has(b.rel_path) || window._manualSwappedPrimaries.has(b.filename))) ? 1 : 0;
                if (isManB !== isManA) return isManB - isManA;

                const pxA = (a.width || 0) * (a.height || 0);
                const pxB = (b.width || 0) * (b.height || 0);
                if (pxB !== pxA) return pxB - pxA;

                const szA = a.size_bytes || 0;
                const szB = b.size_bytes || 0;
                if (szB !== szA) return szB - szA;

                const metaA = (a.starred ? 1 : 0) + (a.sender_jid ? 1 : 0);
                const metaB = (b.starred ? 1 : 0) + (b.sender_jid ? 1 : 0);
                if (metaB !== metaA) return metaB - metaA;

                const cleanA = /_dup\d+/i.test(a.filename || '') ? 0 : 1;
                const cleanB = /_dup\d+/i.test(b.filename || '') ? 0 : 1;
                if (cleanB !== cleanA) return cleanB - cleanA;

                const timeA = a.received_at || '9999-99-99';
                const timeB = b.received_at || '9999-99-99';
                return timeB.localeCompare(timeA);
            });

            const primary = cluster[0];
            const primaryKey = primary.rel_path || primary.filename;
            primarySet.add(primaryKey);
            if (primary.filename) primarySet.add(primary.filename);

            for (let k = 1; k < cluster.length; k++) {
                const dup = cluster[k];
                if (!isValidDuplicateCandidate(primary, dup)) continue;
                const dupKey = dup.rel_path || dup.filename;
                if (dupKey === primaryKey || dup.rel_path === primary.rel_path || primarySet.has(dupKey) || primarySet.has(dup.filename)) continue;
                chatDupSet.add(dupKey);

                let reason = 'quality';
                if (dup.md5 && primary.md5 && dup.md5 === primary.md5) {
                    reason = 'exact';
                } else if (isVideoItem(dup)) {
                    reason = (dup.size_bytes !== primary.size_bytes) ? 'quality' : 'exact';
                } else if (dup.phash && primary.phash && hexHammingDist(dup.phash, primary.phash) <= 4) {
                    reason = (dup.size_bytes === primary.size_bytes) ? 'perceptual' : 'quality';
                } else if (/_dup\d+/i.test(dup.filename || '')) {
                    reason = 'collision';
                }
                dupInfoMap[dupKey] = {
                    primaryFilename: primary.filename,
                    reason: dup.duplicate_reason || reason,
                };
            }
        }
    });

    // Also flag backend duplicates that have duplicate_primary set
    mediaList.forEach(item => {
        if (!isImageItem(item) && !isVideoItem(item)) return;
        if (item.is_duplicate && item.duplicate_primary) {
            const primary = mediaList.find(m => m.filename === item.duplicate_primary);
            if (primary && !isValidDuplicateCandidate(primary, item)) {
                return;
            }
            const k = item.rel_path || item.filename;
            if (primarySet.has(k) || primarySet.has(item.filename)) {
                return;
            }
            if (window._ignoredDupKeys && (window._ignoredDupKeys.has(k) || window._ignoredDupKeys.has(item.filename))) {
                return;
            }
            chatDupSet.add(k);
            if (!dupInfoMap[k]) {
                dupInfoMap[k] = {
                    primaryFilename: item.duplicate_primary,
                    reason: item.duplicate_reason || 'quality',
                };
            }
        }
    });

    // Assemble duplicate groups for side-by-side review
    const duplicateGroups = [];
    const groupedPrimaryNames = new Set();
    clusterMap.forEach(cluster => {
        if (cluster.length > 1) {
            const primary = cluster[0];
            const validDups = cluster.slice(1).filter(dup => isValidDuplicateCandidate(primary, dup));
            if (validDups.length > 0) {
                duplicateGroups.push({
                    primary: primary,
                    duplicates: validDups
                });
                groupedPrimaryNames.add(primary.filename);
            }
        }
    });

    // Also include any backend-flagged duplicates not caught in in-memory clusters
    const backendPairs = new Map();
    mediaList.forEach(item => {
        if (!isImageItem(item) && !isVideoItem(item)) return;
        if (item.is_duplicate && item.duplicate_primary && !groupedPrimaryNames.has(item.duplicate_primary)) {
            const primary = mediaList.find(m => m.filename === item.duplicate_primary);
            if (!primary || !isValidDuplicateCandidate(primary, item)) return;
            if (!backendPairs.has(item.duplicate_primary)) {
                backendPairs.set(item.duplicate_primary, []);
            }
            backendPairs.get(item.duplicate_primary).push(item);
        }
    });
    backendPairs.forEach((dups, primaryName) => {
        const primaryItem = mediaList.find(m => m.filename === primaryName);
        if (primaryItem) {
            const validDups = dups.filter(dup => isValidDuplicateCandidate(primaryItem, dup));
            if (validDups.length > 0) {
                duplicateGroups.push({
                    primary: primaryItem,
                    duplicates: validDups
                });
            }
        }
    });

    // Primary files must NEVER be marked as duplicates
    primarySet.forEach(pKey => {
        chatDupSet.delete(pKey);
        delete dupInfoMap[pKey];
    });
    const validDuplicateGroups = duplicateGroups.filter(grp => !chatDupSet.has(grp.primary.rel_path || grp.primary.filename));

    const result = { chatDupSet, dupInfoMap, duplicateGroups: validDuplicateGroups };
    chat._dupCache = result;
    return result;
}
