/**
 * Injected Script chạy trực tiếp bên trong trang truyện tranh (WebView).
 * Đồng bộ 100% kiến trúc của Extension Chrome (content.ts, adapters.ts, geometry.ts, typography.ts):
 * - Lọc ảnh truyện chuẩn bằng AND (width >= 240 && height >= 260) + loại trừ banner/logo/header nhỏ.
 * - Hỗ trợ đầy đủ <amp-img>, data-src, data-original, srcset của Baozimh & Hivetoons.
 * - Hiển thị khung viền mờ (.ctvn-page-frame) bao quanh từng trang truyện và nhãn trạng thái
 *   "Đang dịch Trang #X..." giống hệt Chrome Extension để biết chính xác đang dịch trang nào.
 * - Hệ tọa độ chuẩn [x1, y1, x2, y2], khử chồng lấn (resolveBoxCollisions),
 *   mở rộng hộp thoại dọc (adjustVerticalBoundingBox) và tự động co giãn chữ (fitTextInBox).
 */
export const MANGA_INJECTED_JS = `
(function() {
  // 1. Nhúng hoặc cập nhật Style chuẩn của Extension Chrome + Khung viền mờ bao quanh trang
  let style = document.getElementById('ctvn-mobile-styles');
  if (!style) {
    style = document.createElement('style');
    style.id = 'ctvn-mobile-styles';
    document.head.appendChild(style);
  }
  style.textContent = \`
    @import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@500;600;700&display=swap');

    @keyframes ctvnSpin {
      to { transform: rotate(360deg); }
    }

    @keyframes ctvnPop {
      0% { transform: scale(0.7); opacity: 0; }
      100% { transform: scale(1); opacity: 1; }
    }

    @keyframes ctvnPulseBorder {
      0%, 100% {
        border-color: rgba(249, 115, 22, 0.95);
        background: rgba(249, 115, 22, 0.09);
      }
      50% {
        border-color: rgba(251, 146, 60, 0.55);
        background: rgba(249, 115, 22, 0.03);
      }
    }

    .ctvn-overlay-layer {
      position: absolute !important;
      pointer-events: none !important;
      z-index: 99990 !important;
      overflow: visible !important;
    }

    /* Khung viền mờ bao quanh trang truyện giống Extension */
    .ctvn-page-frame {
      position: absolute !important;
      pointer-events: none !important;
      box-sizing: border-box !important;
      z-index: 99985 !important;
      border: 1.5px dashed rgba(148, 163, 184, 0.45) !important;
      border-radius: 4px !important;
      transition: all 0.2s ease !important;
    }

    .ctvn-page-frame.is-translating {
      border: 2.5px dashed rgba(249, 115, 22, 0.95) !important;
      background: rgba(249, 115, 22, 0.08) !important;
      box-shadow: inset 0 0 0 2px rgba(249, 115, 22, 0.22), 0 0 16px rgba(249, 115, 22, 0.3) !important;
      animation: ctvnPulseBorder 1.4s ease-in-out infinite !important;
    }

    .ctvn-page-frame.is-translated {
      border: 1.5px dashed rgba(16, 185, 129, 0.65) !important;
      background: transparent !important;
      box-shadow: inset 0 0 0 1px rgba(16, 185, 129, 0.15) !important;
    }

    /* Nhãn nhỏ gọn ở góc trên của khung trang */
    .ctvn-page-badge {
      position: absolute !important;
      top: 8px !important;
      right: 8px !important;
      z-index: 99998 !important;
      display: inline-flex !important;
      align-items: center !important;
      gap: 5px !important;
      background: rgba(15, 23, 42, 0.68) !important;
      backdrop-filter: blur(6px) !important;
      -webkit-backdrop-filter: blur(6px) !important;
      color: #F8FAFC !important;
      border: 1px solid rgba(255, 255, 255, 0.22) !important;
      border-radius: 999px !important;
      padding: 3px 9px !important;
      font-family: 'Be Vietnam Pro', -apple-system, BlinkMacSystemFont, sans-serif !important;
      font-size: 10px !important;
      font-weight: 600 !important;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2) !important;
      pointer-events: auto !important;
      user-select: none !important;
      cursor: pointer !important;
    }

    .ctvn-page-badge.is-translating {
      left: 8px !important;
      right: auto !important;
      background: rgba(255, 255, 255, 0.96) !important;
      color: #0F172A !important;
      border: 1.5px solid #F97316 !important;
      padding: 4px 10px !important;
      font-size: 10.5px !important;
      font-weight: 700 !important;
      box-shadow: 0 3px 10px rgba(249, 115, 22, 0.3) !important;
    }

    .ctvn-page-badge.is-translated {
      background: rgba(5, 150, 105, 0.82) !important;
      color: #FFFFFF !important;
      border-color: rgba(167, 243, 208, 0.6) !important;
    }

    .ctvn-spinner-dot {
      width: 9px !important;
      height: 9px !important;
      border: 2px solid rgba(249, 115, 22, 0.3) !important;
      border-top-color: #F97316 !important;
      border-radius: 50% !important;
      animation: ctvnSpin 0.75s linear infinite !important;
      display: inline-block !important;
    }

    .ctvn-bubble-box {
      position: absolute !important;
      box-sizing: border-box !important;
      background: rgba(255, 255, 255, 0.96) !important;
      color: #111827 !important;
      border: 1.5px solid rgba(31, 41, 55, 0.85) !important;
      border-radius: 8px !important;
      padding: 3px 5px !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      text-align: center !important;
      font-family: 'Be Vietnam Pro', -apple-system, BlinkMacSystemFont, sans-serif !important;
      font-weight: 700 !important;
      line-height: 1.22 !important;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22) !important;
      pointer-events: auto !important;
      user-select: none !important;
      word-break: break-word !important;
      overflow: hidden !important;
      animation: ctvnPop 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
    }

    .ctvn-bubble-box.original-mode {
      background: #FEF3C7 !important;
      color: #92400E !important;
      border-color: #D97706 !important;
    }
  \`;

  const EXCLUDED_TOKEN_REGEX = /\\b(avatar|logo|icon|banner|ads|advert|qrcode|thumb-small|emoji|button)\\b/i;

  function resolveRelativeUrl(url, baseUri) {
    if (!url) return '';
    if (
      url.startsWith('http://') ||
      url.startsWith('https://') ||
      url.startsWith('blob:') ||
      url.startsWith('data:')
    ) {
      return normalizeBaozimhCdnUrl(url);
    }
    try {
      return normalizeBaozimhCdnUrl(new URL(url, baseUri || window.location.href).href);
    } catch (e) {
      return normalizeBaozimhCdnUrl(url);
    }
  }

  // Chuẩn hóa tên miền CDN phụ bị chặn/sập của Baozimh (ví dụ s1-mha1-nlams.bzcdn.net -> s1.bzcdn.net)
  function normalizeBaozimhCdnUrl(url) {
    if (!url || typeof url !== 'string') return '';
    return url.replace(/^https?:\\/\\/s([12])-[a-z0-9-]+\\.bzcdn\\.net\\//i, 'https://s$1.bzcdn.net/');
  }

  // 2. Trích xuất URL ảnh tốt nhất (ưu tiên currentSrc thực tế đã tải thành công trước khi đọc data-src cũ)
  function extractBestImageUrl(img) {
    if (!img) return '';

    const direct = (img.currentSrc || img.getAttribute('src') || img.src || '').trim();
    const isRealUrl = function(u) {
      return u && !u.startsWith('data:image/gif') && !u.startsWith('data:image/svg') && !u.startsWith('about:');
    };

    // Nếu trình duyệt đã tải xong ảnh thực tế (hoặc script trang đã đổi sang CDN dự phòng), ưu tiên currentSrc/src
    if (isRealUrl(direct) && ((img.complete && img.naturalWidth > 100) || !direct.includes('-mha1-'))) {
      const resolvedDirect = resolveRelativeUrl(direct, img.baseURI);
      if (resolvedDirect && !resolvedDirect.includes('placeholder')) {
        return resolvedDirect;
      }
    }

    const lazyAttrs = ['data-src', 'data-original', 'data-lazy-src', 'data-url', 'data-echo'];
    for (const attr of lazyAttrs) {
      const val = (img.getAttribute(attr) || '').trim();
      if (isRealUrl(val)) {
        return resolveRelativeUrl(val, img.baseURI);
      }
    }

    const srcset = (img.getAttribute('data-srcset') || img.getAttribute('srcset') || '').trim();
    if (srcset) {
      const candidates = srcset
        .split(',')
        .map(part => part.trim().split(/\\s+/)[0])
        .filter(Boolean);
      if (candidates.length > 0) {
        return resolveRelativeUrl(candidates[candidates.length - 1], img.baseURI);
      }
    }

    const ampParent = img.closest && img.closest('amp-img');
    if (ampParent) {
      const ampSrc = (ampParent.getAttribute('src') || '').trim();
      if (isRealUrl(ampSrc)) {
        return resolveRelativeUrl(ampSrc, img.baseURI);
      }
      for (const attr of lazyAttrs) {
        const val = (ampParent.getAttribute(attr) || '').trim();
        if (isRealUrl(val)) {
          return resolveRelativeUrl(val, img.baseURI);
        }
      }
    }

    if (isRealUrl(direct)) {
      return resolveRelativeUrl(direct, img.baseURI);
    }
    return '';
  }

  // 3. Kiểm tra ảnh trang truyện hợp lệ (loại trừ ảnh banner ngang mỏng như header "包子漫画" cao < 240px)
  function isComicCandidateElement(el) {
    if (!(el instanceof HTMLImageElement)) return false;
    const url = extractBestImageUrl(el);
    if (!url || url.startsWith('data:image/gif') || url.startsWith('about:')) return false;

    const meta = (el.className || '') + ' ' + (el.id || '') + ' ' + (el.alt || '') + ' ' + url;
    if (EXCLUDED_TOKEN_REGEX.test(meta)) return false;

    const rect = el.getBoundingClientRect();
    const dispW = el.clientWidth || rect.width || el.width || 0;
    const dispH = el.clientHeight || rect.height || el.height || 0;
    const natW = el.naturalWidth || Number(el.getAttribute('width')) || 0;
    const natH = el.naturalHeight || Number(el.getAttribute('height')) || 0;

    const effectiveW = Math.max(dispW, natW);
    const effectiveH = Math.max(dispH, natH);

    // Bắt buộc CẢ chiều rộng VÀ chiều cao đạt ngưỡng trang truyện (loại bỏ banner ngang mỏng ở đầu chương)
    if (dispH > 0 && dispH < 210 && natH > 0 && natH < 260) {
      return false;
    }
    return effectiveW >= 240 && effectiveH >= 260;
  }

  // 3b. Tìm danh sách ảnh truyện tranh trên trang
  function findComicImages() {
    const selectors = [
      '.comic-contain img',
      '.chapter-img img',
      'amp-img img',
      '.reading-content img',
      '.chapter-content img',
      '.read-container img',
      '#chapter-content img',
      '.vung-doc img',
      '.reader-area img',
      '.content__comic img',
      'img[data-src]',
      'main img',
      'article img',
      'img'
    ];

    const found = [];
    for (const sel of selectors) {
      const list = document.querySelectorAll(sel);
      for (const el of list) {
        if (isComicCandidateElement(el) && !found.includes(el)) {
          found.push(el);
        }
      }
      if (found.length > 0 && sel !== 'img') break;
    }

    if (found.length === 0) {
      const allImgs = document.querySelectorAll('img');
      for (const el of allImgs) {
        if (isComicCandidateElement(el) && !found.includes(el)) {
          found.push(el);
        }
      }
    }

    found.forEach((img, idx) => {
      img.setAttribute('data-ctvn-page-index', String(idx + 1));
    });

    return found;
  }

  // 3c. Tìm ảnh đang hiển thị nhiều nhất trong viewport
  function findTargetImageInViewport(images) {
    if (!images || images.length === 0) return null;
    const vh = window.innerHeight || document.documentElement.clientHeight || 800;
    let bestImg = null;
    let bestScore = -1;

    for (const img of images) {
      const rect = img.getBoundingClientRect();
      if (rect.height < 180 || rect.width < 180) continue;
      const visibleTop = Math.max(0, rect.top);
      const visibleBottom = Math.min(vh, rect.bottom);
      const visibleHeight = Math.max(0, visibleBottom - visibleTop);
      if (visibleHeight > 0) {
        const viewportCenter = vh / 2;
        const imgCenter = (visibleTop + visibleBottom) / 2;
        const centerBonus = Math.max(0, 1 - Math.abs(imgCenter - viewportCenter) / vh) * 60;
        const score = visibleHeight + centerBonus;
        if (score > bestScore) {
          bestScore = score;
          bestImg = img;
        }
      }
    }

    if (bestImg) return bestImg;
    return images[0];
  }

  // 3d. Lấy thẻ container bao ngoài hợp lý (hỗ trợ cả <amp-img> trên Baozimh để không bị che khuất)
  function getStageContainer(img) {
    if (!img) return null;
    const amp = img.closest && img.closest('amp-img');
    if (amp && amp.parentElement) {
      return amp.parentElement;
    }
    return img.parentElement;
  }

  function getImageOffsetInContainer(img, container) {
    if (!img || !container) return { left: 0, top: 0, width: 360, height: 500 };
    const imgRect = img.getBoundingClientRect();
    const contRect = container.getBoundingClientRect();
    const width = img.clientWidth || imgRect.width || img.width || 360;
    const height = img.clientHeight || imgRect.height || img.height || 500;
    return {
      left: Math.round(imgRect.left - contRect.left + (container.scrollLeft || 0)),
      top: Math.round(imgRect.top - contRect.top + (container.scrollTop || 0)),
      width: Math.round(width),
      height: Math.round(height)
    };
  }

  // 3e. Vẽ khung viền mờ (.ctvn-page-frame) + nhãn trạng thái trên từng trang truyện giống Extension
  function ensurePageBadges() {
    const images = findComicImages();
    images.forEach((img, idx) => {
      const pageNum = idx + 1;
      img.setAttribute('data-ctvn-page-index', String(pageNum));
      const container = getStageContainer(img);
      if (!container) return;

      const computed = window.getComputedStyle(container);
      if (computed.position === 'static') {
        container.style.position = 'relative';
      }

      const pos = getImageOffsetInContainer(img, container);
      if (pos.width < 150 || pos.height < 150) return;

      // 1. Khung viền mờ bao quanh đúng diện tích trang truyện
      const frameId = 'ctvn-frame-page-' + pageNum;
      let frame = container.querySelector('#' + frameId) || container.querySelector('.ctvn-page-frame');
      if (!frame) {
        frame = document.createElement('div');
        frame.id = frameId;
        frame.className = 'ctvn-page-frame';
        container.appendChild(frame);
      }
      frame.style.left = pos.left + 'px';
      frame.style.top = pos.top + 'px';
      frame.style.width = pos.width + 'px';
      frame.style.height = pos.height + 'px';

      // 2. Huy hiệu nhỏ gọn trên góc khung
      const badgeId = 'ctvn-badge-page-' + pageNum;
      let badge = frame.querySelector('#' + badgeId) || frame.querySelector('.ctvn-page-badge');
      if (!badge) {
        badge = document.createElement('div');
        badge.id = badgeId;
        badge.className = 'ctvn-page-badge';
        badge.onclick = function(e) {
          e.preventDefault();
          e.stopPropagation();
          if (img.getAttribute('data-ctvn-status') === 'translated') {
            const layer = container.querySelector('.ctvn-overlay-layer');
            if (layer) {
              const isHidden = layer.style.display === 'none';
              layer.style.display = isHidden ? 'block' : 'none';
              badge.innerHTML = isHidden
                ? '✓ Trang #' + pageNum + ' • Đã dịch'
                : '👁️ Trang #' + pageNum + ' • Bản gốc';
              return;
            }
          }
          window.__triggerTranslateSpecificImage(img);
        };
        frame.appendChild(badge);
      }

      const status = img.getAttribute('data-ctvn-status') || 'idle';
      if (status === 'translating') {
        frame.className = 'ctvn-page-frame is-translating';
        badge.className = 'ctvn-page-badge is-translating';
        badge.innerHTML = '<span class="ctvn-spinner-dot"></span><span>Đang dịch Trang #' + pageNum + '...</span>';
      } else if (status === 'translated') {
        const layer = container.querySelector('.ctvn-overlay-layer');
        const isHidden = layer && layer.style.display === 'none';
        frame.className = 'ctvn-page-frame is-translated';
        badge.className = 'ctvn-page-badge is-translated';
        const cnt = img.getAttribute('data-ctvn-block-count') || '';
        badge.innerHTML = isHidden
          ? '👁️ Trang #' + pageNum + ' • Ảnh gốc'
          : '✓ Trang #' + pageNum + (cnt ? ' (' + cnt + ' thoại)' : ' • Đã dịch');
      } else {
        frame.className = 'ctvn-page-frame';
        badge.className = 'ctvn-page-badge';
        badge.innerHTML = 'Trang #' + pageNum + ' • Dịch';
      }
    });
  }

  // 4. Các hàm Geometry & Typography đồng bộ từ Chrome Extension
  function scaleBboxToDisplay(bbox, naturalW, naturalH, displayW, displayH) {
    const safeNatW = naturalW > 0 ? naturalW : displayW || 1;
    const safeNatH = naturalH > 0 ? naturalH : displayH || 1;
    const scaleX = displayW / safeNatW;
    const scaleY = displayH / safeNatH;

    // bbox chuẩn từ Server: [x1, y1, x2, y2]
    const [x1, y1, x2, y2] = bbox;
    return {
      left: x1 * scaleX,
      top: y1 * scaleY,
      width: Math.max(18, (x2 - x1) * scaleX),
      height: Math.max(18, (y2 - y1) * scaleY)
    };
  }

  function adjustVerticalBoundingBox(box, displayW) {
    const { left, top, width, height } = box;
    if (width <= 0) return box;
    const ratio = height / width;
    if (ratio > 1.8) {
      const targetWidth = Math.min(height * 0.72, width * 1.45);
      const deltaW = targetWidth - width;
      let newLeft = left - deltaW / 2;
      if (displayW && displayW > 0) {
        newLeft = Math.max(2, Math.min(newLeft, displayW - targetWidth - 2));
      } else {
        newLeft = Math.max(2, newLeft);
      }
      return {
        left: newLeft,
        top: top,
        width: targetWidth,
        height: height
      };
    }
    return box;
  }

  function resolveBoxCollisions(boxes, minGap) {
    const gap = typeof minGap === 'number' ? minGap : 2;
    const result = boxes.map(b => ({ left: b.left, top: b.top, width: b.width, height: b.height }));
    const n = result.length;
    if (n <= 1) return result;

    for (let pass = 0; pass < 3; pass++) {
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = result[i];
          const b = result[j];

          const overlapX = Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left);
          const overlapY = Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top);

          if (overlapX > -gap && overlapY > -gap) {
            const needX = overlapX + gap;
            const needY = overlapY + gap;

            if (needX < needY) {
              const aCenterX = a.left + a.width / 2;
              const bCenterX = b.left + b.width / 2;
              const midX = (Math.max(a.left, b.left) + Math.min(a.left + a.width, b.left + b.width)) / 2;
              if (aCenterX <= bCenterX) {
                const newAWidth = Math.max(24, midX - gap / 2 - a.left);
                const newBLeft = midX + gap / 2;
                const newBWidth = Math.max(24, b.left + b.width - newBLeft);
                a.width = newAWidth;
                b.left = newBLeft;
                b.width = newBWidth;
              } else {
                const newBWidth = Math.max(24, midX - gap / 2 - b.left);
                const newALeft = midX + gap / 2;
                const newAWidth = Math.max(24, a.left + a.width - newALeft);
                b.width = newBWidth;
                a.left = newALeft;
                a.width = newAWidth;
              }
            } else {
              const aCenterY = a.top + a.height / 2;
              const bCenterY = b.top + b.height / 2;
              const midY = (Math.max(a.top, b.top) + Math.min(a.top + a.height, b.top + b.height)) / 2;
              if (aCenterY <= bCenterY) {
                const newAHeight = Math.max(20, midY - gap / 2 - a.top);
                const newBTop = midY + gap / 2;
                const newBHeight = Math.max(20, b.top + b.height - newBTop);
                a.height = newAHeight;
                b.top = newBTop;
                b.height = newBHeight;
              } else {
                const newBHeight = Math.max(20, midY - gap / 2 - b.top);
                const newATop = midY + gap / 2;
                const newAHeight = Math.max(20, a.top + a.height - newATop);
                b.height = newBHeight;
                a.top = newATop;
                a.height = newAHeight;
              }
            }
          }
        }
      }
    }
    return result;
  }

  function fitTextInBox(text, boxWidth, boxHeight, minFont, maxFont) {
    minFont = minFont || 9;
    maxFont = maxFont || 15;
    const clean = (text || '').trim().replace(/\\s+/g, ' ');
    if (!clean || boxWidth <= 0 || boxHeight <= 0) {
      return { fontSize: minFont, lines: clean ? [clean] : [] };
    }

    const padX = Math.min(10, Math.max(4, boxWidth * 0.08));
    const padY = Math.min(8, Math.max(4, boxHeight * 0.08));
    const usableW = Math.max(16, boxWidth - padX);
    const usableH = Math.max(14, boxHeight - padY);
    const charWidthRatio = 0.54;
    const lineHeightRatio = 1.22;

    const words = clean.split(' ');

    function wrapWords(fontSize) {
      const maxCharsPerLine = Math.max(1, Math.floor(usableW / (fontSize * charWidthRatio)));
      const lines = [];
      let currentLine = '';

      for (const word of words) {
        if (!currentLine) {
          if (word.length > maxCharsPerLine) {
            let rem = word;
            while (rem.length > maxCharsPerLine) {
              lines.push(rem.slice(0, maxCharsPerLine));
              rem = rem.slice(maxCharsPerLine);
            }
            currentLine = rem;
          } else {
            currentLine = word;
          }
        } else if ((currentLine + ' ' + word).length <= maxCharsPerLine) {
          currentLine += ' ' + word;
        } else {
          lines.push(currentLine);
          if (word.length > maxCharsPerLine) {
            let rem = word;
            while (rem.length > maxCharsPerLine) {
              lines.push(rem.slice(0, maxCharsPerLine));
              rem = rem.slice(maxCharsPerLine);
            }
            currentLine = rem;
          } else {
            currentLine = word;
          }
        }
      }
      if (currentLine) lines.push(currentLine);
      return lines;
    }

    let low = minFont;
    let high = maxFont;
    let bestFont = minFont;
    let bestLines = wrapWords(minFont);

    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const lines = wrapWords(mid);
      const totalHeight = lines.length * mid * lineHeightRatio;
      if (totalHeight <= usableH) {
        bestFont = mid;
        bestLines = lines;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }

    return { fontSize: bestFont, lines: bestLines };
  }

  // 4b. Trích xuất ảnh trực tiếp từ bộ nhớ đệm Chromium WebView (giống fetchImageBlobInBackground của Extension)
  // giúp không cần mở lại kết nối TCP mới từ Android Native OkHttp tới CDN bị chặn.
  function tryExtractImageDataUrlInWebView(primaryUrl) {
    return new Promise(function(resolve) {
      if (!primaryUrl || primaryUrl.startsWith('data:')) {
        resolve(primaryUrl || '');
        return;
      }

      const candidates = [primaryUrl];
      if (/^https?:\\/\\/[^/]*bzcdn\\.net\\//i.test(primaryUrl)) {
        const s2 = primaryUrl.replace(/^https?:\\/\\/[^/]*bzcdn\\.net\\//i, 'https://s2.bzcdn.net/');
        const s1 = primaryUrl.replace(/^https?:\\/\\/[^/]*bzcdn\\.net\\//i, 'https://s1.bzcdn.net/');
        if (!candidates.includes(s2)) candidates.push(s2);
        if (!candidates.includes(s1)) candidates.push(s1);
      }

      let idx = 0;
      function tryNext() {
        if (idx >= candidates.length) {
          resolve('');
          return;
        }
        const currentCandidate = candidates[idx++];
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        const timer = setTimeout(function() {
          if (controller) controller.abort();
        }, 3500);

        fetch(currentCandidate, {
          method: 'GET',
          credentials: 'omit',
          cache: 'force-cache',
          signal: controller ? controller.signal : undefined
        })
          .then(function(resp) {
            clearTimeout(timer);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.blob();
          })
          .then(function(blob) {
            if (!blob || blob.size < 512) throw new Error('Empty blob');
            const reader = new FileReader();
            reader.onloadend = function() {
              const res = typeof reader.result === 'string' ? reader.result : '';
              if (res && res.startsWith('data:image/')) {
                resolve(res);
              } else {
                tryNext();
              }
            };
            reader.onerror = function() {
              tryNext();
            };
            reader.readAsDataURL(blob);
          })
          .catch(function() {
            clearTimeout(timer);
            tryNext();
          });
      }

      tryNext();
    });
  }

  // 5. Kích hoạt dịch cho 1 ảnh cụ thể và hiển thị khung viền mờ bao quanh trang đang dịch
  window.__triggerTranslateSpecificImage = function(targetImg) {
    const images = findComicImages();
    if (!targetImg) {
      targetImg = findTargetImageInViewport(images) || images[0];
    }
    if (!targetImg) {
      if (window.ReactNativeWebView) {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'ERROR',
          message: 'Không tìm thấy ảnh truyện tranh nào trên trang này.'
        }));
      }
      return;
    }

    const pageIndex = Number(targetImg.getAttribute('data-ctvn-page-index') || (images.indexOf(targetImg) + 1) || 1);

    // Đánh dấu ảnh đang được dịch và bật khung viền mờ + huy hiệu "Đang dịch Trang #X..."
    images.forEach(img => {
      img.removeAttribute('data-ctvn-active-target');
      if (img.getAttribute('data-ctvn-status') === 'translating') {
        img.setAttribute('data-ctvn-status', 'idle');
      }
    });
    targetImg.setAttribute('data-ctvn-active-target', 'true');
    targetImg.setAttribute('data-ctvn-status', 'translating');
    ensurePageBadges();

    // Đảm bảo ảnh gốc không bị ẩn bởi script lazy-load
    const bestUrl = extractBestImageUrl(targetImg);
    if (bestUrl && (!targetImg.getAttribute('src') || targetImg.getAttribute('src').startsWith('data:image/gif'))) {
      targetImg.src = bestUrl;
    }
    targetImg.style.setProperty('visibility', 'visible', 'important');
    targetImg.style.setProperty('display', 'block', 'important');
    targetImg.style.setProperty('opacity', '1', 'important');

    // Dọn dẹp placeholder che mờ ảnh (như .placeholder trên Baozimh)
    const container = getStageContainer(targetImg);
    if (container) {
      container.querySelectorAll('.placeholder, .lazyloading, [class*="placeholder"]').forEach(function(ph) {
        if (ph !== targetImg) ph.remove();
      });
    }

    if (!bestUrl) {
      targetImg.setAttribute('data-ctvn-status', 'idle');
      ensurePageBadges();
      if (window.ReactNativeWebView) {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'ERROR',
          message: 'Không lấy được đường dẫn URL của ảnh truyện.'
        }));
      }
      return;
    }

    // Thử lấy trực tiếp dữ liệu ảnh từ bộ nhớ đệm của WebView trước, sau đó gửi về React Native
    tryExtractImageDataUrlInWebView(bestUrl).then(function(dataUrl) {
      if (window.ReactNativeWebView) {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'TRANSLATE_PAGE_REQUEST',
          imageUrl: bestUrl,
          imageDataUrl: dataUrl || '',
          pageIndex: pageIndex,
          refererOrigin: window.location.origin,
          pageTitle: document.title || 'Truyện tranh',
          pageUrl: window.location.href
        }));
      }
    });
  };

  window.__triggerTranslateActivePage = function() {
    const images = findComicImages();
    const targetImg = findTargetImageInViewport(images) || images[0];
    window.__triggerTranslateSpecificImage(targetImg);
  };

  window.__clearTranslatingStatus = function() {
    const targetImg = document.querySelector('img[data-ctvn-active-target="true"]');
    if (targetImg && targetImg.getAttribute('data-ctvn-status') === 'translating') {
      targetImg.setAttribute('data-ctvn-status', 'idle');
    }
    ensurePageBadges();
  };

  let lastRenderedState = null;
  let activeResizeObserver = null;

  // 5b. Ẩn / Hiện toàn bộ lớp đè bong bóng thoại để xem ảnh gốc nguyên bản (giống hệt Extension)
  window.__setShowOriginalMode = function(showOriginal) {
    const isOrig = !!showOriginal;
    if (lastRenderedState) {
      lastRenderedState.showOriginal = isOrig;
    }
    const layers = document.querySelectorAll('.ctvn-overlay-layer');
    layers.forEach(function(layer) {
      layer.style.display = isOrig ? 'none' : 'block';
    });
    ensurePageBadges();
  };

  // 6. Vẽ đè các khối thoại lên đúng trang truyện
  window.__renderRealTranslatedBlocks = function(blocks, showOriginal) {
    const images = findComicImages();
    if (images.length === 0) return;

    const targetImg = document.querySelector('img[data-ctvn-active-target="true"]') || findTargetImageInViewport(images) || images[0];
    const container = getStageContainer(targetImg);
    if (!container) return;

    lastRenderedState = { blocks: blocks, showOriginal: !!showOriginal };

    targetImg.style.setProperty('visibility', 'visible', 'important');
    targetImg.style.setProperty('display', 'block', 'important');
    targetImg.style.setProperty('opacity', '1', 'important');

    // Dọn dẹp layer cũ nếu có
    const oldLayers = container.querySelectorAll('.ctvn-overlay-layer');
    oldLayers.forEach(l => l.remove());

    if (!blocks || blocks.length === 0) {
      targetImg.setAttribute('data-ctvn-status', 'idle');
      ensurePageBadges();
      return;
    }

    const validBlocks = blocks.filter(blk => {
      if (!blk || !Array.isArray(blk.bbox) || blk.bbox.length < 4) return false;
      const hasTrans = blk.translation && String(blk.translation).trim().length > 0;
      const hasSrc = blk.source_text && String(blk.source_text).trim().length > 0;
      return hasTrans || hasSrc;
    });

    if (validBlocks.length === 0) {
      targetImg.setAttribute('data-ctvn-status', 'idle');
      ensurePageBadges();
      return;
    }

    targetImg.setAttribute('data-ctvn-status', 'translated');
    targetImg.setAttribute('data-ctvn-block-count', String(validBlocks.length));
    ensurePageBadges();

    const computed = window.getComputedStyle(container);
    if (computed.position === 'static') {
      container.style.position = 'relative';
    }

    const pos = getImageOffsetInContainer(targetImg, container);
    const natW = targetImg.naturalWidth || pos.width || 800;
    const natH = targetImg.naturalHeight || pos.height || 1200;
    const dispW = pos.width || targetImg.clientWidth || natW;
    const dispH = pos.height || targetImg.clientHeight || natH;

    const overlayLayer = document.createElement('div');
    overlayLayer.className = 'ctvn-overlay-layer';
    overlayLayer.style.position = 'absolute';
    overlayLayer.style.left = pos.left + 'px';
    overlayLayer.style.top = pos.top + 'px';
    overlayLayer.style.width = dispW + 'px';
    overlayLayer.style.height = dispH + 'px';
    overlayLayer.style.pointerEvents = 'none';
    overlayLayer.style.zIndex = '99990';
    overlayLayer.style.display = showOriginal ? 'none' : 'block';

    const rawBoxes = validBlocks.map(blk => {
      const scaled = scaleBboxToDisplay(blk.bbox, natW, natH, dispW, dispH);
      return adjustVerticalBoundingBox(scaled, dispW);
    });

    const finalBoxes = resolveBoxCollisions(rawBoxes, 2);

    container.appendChild(overlayLayer);

    validBlocks.forEach((blk, idx) => {
      const box = finalBoxes[idx];
      const text = blk.translation || blk.source_text || '';
      if (!text.trim()) return;

      const fitted = fitTextInBox(text, box.width, box.height, 9, 15);

      const bubble = document.createElement('div');
      bubble.className = 'ctvn-bubble-box';
      bubble.id = 'ctvn-bubble-' + idx;
      bubble.style.left = Math.round(box.left) + 'px';
      bubble.style.top = Math.round(box.top) + 'px';
      bubble.style.width = Math.round(box.width) + 'px';
      bubble.style.height = Math.round(box.height) + 'px';
      bubble.style.fontSize = fitted.fontSize + 'px';
      bubble.innerText = text;

      overlayLayer.appendChild(bubble);

      let currentFontSize = fitted.fontSize;
      let guard = 0;
      while (
        (bubble.scrollHeight > bubble.offsetHeight + 2 || bubble.scrollWidth > bubble.offsetWidth + 2) &&
        currentFontSize > 8.5 &&
        guard < 16
      ) {
        currentFontSize -= 0.5;
        bubble.style.fontSize = currentFontSize + 'px';
        guard++;
      }

      if (bubble.scrollHeight > bubble.offsetHeight + 2) {
        bubble.style.height = 'auto';
        bubble.style.minHeight = Math.round(box.height) + 'px';
      }
    });

    ensurePageBadges();

    if (typeof ResizeObserver !== 'undefined') {
      if (activeResizeObserver) {
        activeResizeObserver.disconnect();
      }
      let lastW = dispW;
      let lastH = dispH;
      activeResizeObserver = new ResizeObserver(() => {
        const curW = targetImg.clientWidth || targetImg.width;
        const curH = targetImg.clientHeight || targetImg.height;
        if (Math.abs(curW - lastW) > 4 || Math.abs(curH - lastH) > 4) {
          lastW = curW;
          lastH = curH;
          ensurePageBadges();
          if (lastRenderedState) {
            window.__renderRealTranslatedBlocks(lastRenderedState.blocks, lastRenderedState.showOriginal);
          }
        }
      });
      activeResizeObserver.observe(targetImg);
    }
  };

  ensurePageBadges();
  setTimeout(ensurePageBadges, 600);
  setTimeout(ensurePageBadges, 1800);

  if (!window.__COMIC_TRANSLATE_MOBILE_INJECTED) {
    window.__COMIC_TRANSLATE_MOBILE_INJECTED = true;
    let badgeTimer = null;
    window.addEventListener('scroll', function() {
      if (badgeTimer) return;
      badgeTimer = setTimeout(function() {
        badgeTimer = null;
        ensurePageBadges();
      }, 350);
    }, { passive: true });
  }

  if (window.ReactNativeWebView) {
    window.ReactNativeWebView.postMessage(JSON.stringify({
      type: 'PAGE_READY',
      url: window.location.href,
      title: document.title || 'Comic Reader'
    }));
  }
})();
true;
`;
