/**
 * Injected Script chạy trực tiếp bên trong trang truyện tranh (WebView).
 * Tuân thủ 100% chuẩn của Extension Chrome (content.ts):
 * - KHÔNG di chuyển (reparent) thẻ <img> để tránh làm hỏng DOM và Lazy-loader của trang web.
 * - Loại bỏ các placeholder/loading element của web truyện che mất ảnh.
 * - Giữ ảnh gốc luôn hiển thị (visibility: visible, display: block).
 * - Vẽ layer bong bóng đè (.ctvn-overlay-layer) chính xác lên đúng trang truyện đang đọc.
 */
export const MANGA_INJECTED_JS = `
(function() {
  if (window.__COMIC_TRANSLATE_MOBILE_INJECTED) return;
  window.__COMIC_TRANSLATE_MOBILE_INJECTED = true;

  // 1. Nhúng Style chuẩn của Extension Chrome
  const style = document.createElement('style');
  style.id = 'ctvn-mobile-styles';
  style.textContent = \`
    @import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@500;600;700&display=swap');

    .ctvn-overlay-layer {
      position: absolute !important;
      pointer-events: none !important;
      z-index: 99999 !important;
      overflow: visible !important;
    }

    .ctvn-bubble-box {
      position: absolute !important;
      box-sizing: border-box !important;
      background: rgba(255, 255, 255, 0.96) !important;
      color: #111827 !important;
      border: 2px solid #1f2937 !important;
      border-radius: 8px !important;
      padding: 3px 5px !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      text-align: center !important;
      font-family: 'Be Vietnam Pro', -apple-system, BlinkMacSystemFont, sans-serif !important;
      font-weight: 700 !important;
      line-height: 1.25 !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.28) !important;
      pointer-events: auto !important;
      user-select: none !important;
      word-break: break-word !important;
      animation: ctvnPop 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
    }

    .ctvn-bubble-box.original-mode {
      background: #FEF3C7 !important;
      color: #92400E !important;
      border-color: #D97706 !important;
    }

    @keyframes ctvnPop {
      0% { transform: scale(0.7); opacity: 0; }
      100% { transform: scale(1); opacity: 1; }
    }
  \`;
  document.head.appendChild(style);

  // 2. Trích xuất URL ảnh tốt nhất
  function extractBestImageUrl(img) {
    if (!img) return '';
    const candidates = [
      img.getAttribute('data-src'),
      img.getAttribute('data-original'),
      img.getAttribute('data-lazy-src'),
      img.getAttribute('data-url'),
      img.currentSrc,
      img.src
    ];
    for (const c of candidates) {
      if (c && typeof c === 'string' && c.trim() && !c.startsWith('data:image/gif')) {
        return c.trim();
      }
    }
    return img.src || '';
  }

  // 3. Tìm danh sách ảnh truyện tranh trên trang
  function findComicImages() {
    const selectors = [
      '.comic-contain img',
      '.read-container img',
      '#chapter-content img',
      '.vung-doc img',
      '.reader-area img',
      '.content__comic img',
      'img[src*="chapter"]',
      'img[src*="comic"]',
      'img[src*="manga"]',
      'main img',
      'article img',
      'img'
    ];

    const found = [];
    for (const sel of selectors) {
      const list = document.querySelectorAll(sel);
      for (const el of list) {
        if (el instanceof HTMLImageElement) {
          const w = el.naturalWidth || el.width || el.clientWidth;
          const h = el.naturalHeight || el.height || el.clientHeight;
          if ((w > 200 || h > 250) && !found.includes(el)) {
            found.push(el);
          }
        }
      }
      if (found.length > 0) break;
    }

    return found.length > 0 ? found : Array.from(document.querySelectorAll('img')).filter(img => (img.clientWidth > 180 || img.naturalWidth > 180));
  }

  // 4. Kích hoạt trích xuất link ảnh
  window.__triggerTranslateActivePage = function() {
    const images = findComicImages();
    if (images.length === 0) {
      if (window.ReactNativeWebView) {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'ERROR',
          message: 'Không tìm thấy ảnh truyện tranh nào trên trang này.'
        }));
      }
      return;
    }

    // Ưu tiên ảnh đang nằm trong tầm nhìn (viewport)
    let targetImg = images[0];
    for (const img of images) {
      const rect = img.getBoundingClientRect();
      if (rect.top >= -100 && rect.top <= window.innerHeight * 0.75) {
        targetImg = img;
        break;
      }
    }

    // Đánh dấu ảnh đang được dịch để lát nữa render đúng vị trí
    images.forEach(img => img.removeAttribute('data-ctvn-active-target'));
    targetImg.setAttribute('data-ctvn-active-target', 'true');

    // Đảm bảo ảnh gốc không bị ẩn bởi script lazy-load
    const bestUrl = extractBestImageUrl(targetImg);
    if (bestUrl && (!targetImg.getAttribute('src') || targetImg.getAttribute('src').startsWith('data:image/gif'))) {
      targetImg.src = bestUrl;
    }
    targetImg.style.setProperty('visibility', 'visible', 'important');
    targetImg.style.setProperty('display', 'block', 'important');
    targetImg.style.setProperty('opacity', '1', 'important');

    // Dọn dẹp placeholder che mờ ảnh (như .placeholder trên Baozimh)
    const parent = targetImg.parentElement;
    if (parent) {
      parent.querySelectorAll('.placeholder, .lazyloading, [class*="placeholder"]').forEach(function(ph) {
        if (ph !== targetImg) ph.remove();
      });
    }

    if (!bestUrl) {
      if (window.ReactNativeWebView) {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'ERROR',
          message: 'Không lấy được đường dẫn URL của ảnh truyện.'
        }));
      }
      return;
    }

    // Gửi imageUrl về React Native
    if (window.ReactNativeWebView) {
      window.ReactNativeWebView.postMessage(JSON.stringify({
        type: 'TRANSLATE_PAGE_REQUEST',
        imageUrl: bestUrl,
        refererOrigin: window.location.origin,
        pageTitle: document.title || 'Truyện tranh',
        pageUrl: window.location.href
      }));
    }
  };

  // 5. Vẽ đè các khối thoại lên đúng trang truyện
  window.__renderRealTranslatedBlocks = function(blocks, showOriginal) {
    const images = findComicImages();
    if (images.length === 0) return;

    // Tìm đúng ảnh vừa được gửi dịch
    const targetImg = document.querySelector('img[data-ctvn-active-target="true"]') || images[0];
    const parent = targetImg.parentElement || targetImg.parentNode;
    if (!parent) return;

    // Đảm bảo ảnh gốc luôn hiển thị rõ nét
    targetImg.style.setProperty('visibility', 'visible', 'important');
    targetImg.style.setProperty('display', 'block', 'important');
    targetImg.style.setProperty('opacity', '1', 'important');

    // Dọn dẹp layer cũ nếu có
    const oldLayers = parent.querySelectorAll('.ctvn-overlay-layer');
    oldLayers.forEach(l => l.remove());

    if (!blocks || blocks.length === 0) return;

    // Đảm bảo parent có position relative để layer định vị chuẩn
    const computed = window.getComputedStyle(parent);
    if (computed.position === 'static') {
      parent.style.position = 'relative';
    }

    const overlayLayer = document.createElement('div');
    overlayLayer.className = 'ctvn-overlay-layer';
    overlayLayer.style.position = 'absolute';
    overlayLayer.style.left = targetImg.offsetLeft + 'px';
    overlayLayer.style.top = targetImg.offsetTop + 'px';
    overlayLayer.style.width = (targetImg.clientWidth || targetImg.width || 800) + 'px';
    overlayLayer.style.height = (targetImg.clientHeight || targetImg.height || 1200) + 'px';
    overlayLayer.style.pointerEvents = 'none';
    overlayLayer.style.zIndex = '99999';

    const natW = targetImg.naturalWidth || 800;
    const natH = targetImg.naturalHeight || 1200;
    const dispW = targetImg.clientWidth || targetImg.width || natW;
    const dispH = targetImg.clientHeight || targetImg.height || natH;

    const scaleX = dispW / natW;
    const scaleY = dispH / natH;

    blocks.forEach((blk, idx) => {
      // bbox: [ymin, xmin, ymax, xmax]
      const [ymin, xmin, ymax, xmax] = blk.bbox;
      let left = xmin * scaleX;
      let top = ymin * scaleY;
      let width = (xmax - xmin) * scaleX;
      let height = (ymax - ymin) * scaleY;

      // Mở rộng viền cho câu thoại tiếng Việt dễ đọc
      if (height / width > 1.3) {
        const expand = Math.max(20, width * 0.5);
        left = Math.max(5, left - expand / 2);
        width += expand;
      }

      width = Math.max(50, width);
      height = Math.max(28, height);

      const bubble = document.createElement('div');
      bubble.className = 'ctvn-bubble-box' + (showOriginal ? ' original-mode' : '');
      bubble.id = 'ctvn-bubble-' + idx;
      bubble.style.left = left + 'px';
      bubble.style.top = top + 'px';
      bubble.style.width = width + 'px';
      bubble.style.minHeight = height + 'px';

      const area = width * height;
      const fontSize = Math.min(16, Math.max(10, Math.floor(Math.sqrt(area) / 4.8)));
      bubble.style.fontSize = fontSize + 'px';

      const text = showOriginal ? blk.source_text : blk.translation;
      bubble.innerText = text || '';

      // Bấm vào bong bóng để xem đối chiếu giữa chữ gốc và câu dịch tiếng Việt
      bubble.onclick = function(e) {
        e.stopPropagation();
        if (bubble.classList.contains('original-mode')) {
          bubble.classList.remove('original-mode');
          bubble.innerText = blk.translation;
        } else {
          bubble.classList.add('original-mode');
          bubble.innerText = blk.source_text;
        }
      };

      overlayLayer.appendChild(bubble);
    });

    parent.appendChild(overlayLayer);
  };

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
