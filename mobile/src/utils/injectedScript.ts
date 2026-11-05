/**
 * Injected Script chạy trực tiếp bên trong trang truyện tranh (WebView).
 * Layout mobile, dùng tọa độ ảnh gốc [x1, y1, x2, y2]:
 * - KHÔNG di chuyển (reparent) thẻ <img> để tránh làm hỏng DOM và Lazy-loader của trang web.
 * - Loại bỏ các placeholder/loading element của web truyện che mất ảnh.
 * - Giữ ảnh gốc luôn hiển thị (visibility: visible, display: block).
 * - Lớp phủ nằm ngoài cây DOM của reader để AMP/lazy-loader không ẩn hoặc xóa nó.
 */
export const MANGA_INJECTED_JS = `
(function() {
  if (window.__COMIC_TRANSLATE_MOBILE_INJECTED) return;
  window.__COMIC_TRANSLATE_MOBILE_INJECTED = true;

  const renderedPages = new Map();
  const pendingTargets = new Map();
  let showingOriginal = false;
  let layoutFrame = 0;
  let autoTranslate = false;
  let autoTarget = null;
  let autoTimer = 0;
  let translationContext = '';
  const completedUrls = new Set();
  const overlayRoot = document.createElement('div');
  overlayRoot.id = 'ctvn-mobile-overlay-root';
  overlayRoot.style.cssText = 'position:fixed!important;inset:0!important;z-index:2147483000!important;pointer-events:none!important;overflow:hidden!important;display:block!important;';
  document.documentElement.appendChild(overlayRoot);

  // Style dành cho màn hình nhỏ, không tự mở rộng ra ngoài khung thoại.
  const style = document.createElement('style');
  style.id = 'ctvn-mobile-styles';
  style.textContent = \`
    .ctvn-overlay-layer {
      position: absolute !important;
      pointer-events: none !important;
      z-index: 99999 !important;
      overflow: hidden !important;
    }

    .ctvn-bubble-box {
      position: absolute !important;
      box-sizing: border-box !important;
      margin: 0 !important;
      min-width: 0 !important;
      min-height: 0 !important;
      max-width: none !important;
      max-height: none !important;
      overflow: hidden !important;
      background: #fff !important;
      color: #111827 !important;
      border: 0 !important;
      border-radius: 0 !important;
      padding: 2px !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      text-align: center !important;
      font-family: 'Be Vietnam Pro', -apple-system, BlinkMacSystemFont, sans-serif !important;
      font-weight: 600 !important;
      line-height: 1.25 !important;
      box-shadow: none !important;
      pointer-events: auto !important;
      user-select: none !important;
      cursor: pointer !important;
      -webkit-text-size-adjust: none !important;
      text-size-adjust: none !important;
    }

    .ctvn-bubble-text {
      display: block !important;
      width: 100% !important;
      padding: 0 !important;
      margin: 0 !important;
      font: inherit !important;
      color: inherit !important;
      line-height: inherit !important;
      white-space: normal !important;
      word-break: normal !important;
      overflow-wrap: normal !important;
      hyphens: none !important;
    }
  \`;
  document.head.appendChild(style);
  // Keep layout CSS available immediately, even when the font CDN is slow/offline.
  const fontLink = document.createElement('link');
  fontLink.rel = 'stylesheet';
  fontLink.href = 'https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@500;600;700&display=swap';
  document.head.appendChild(fontLink);

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
        try { return new URL(c.trim(), document.baseURI).href; } catch { return c.trim(); }
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
  window.__triggerTranslateActivePage = function(automatic) {
    if (automatic && (!autoTranslate || autoTarget)) return;
    const images = findComicImages();
    if (images.length === 0) {
      if (automatic) return;
      if (window.ReactNativeWebView) {
        window.ReactNativeWebView.postMessage(JSON.stringify({
          type: 'ERROR',
          message: 'Không tìm thấy ảnh truyện tranh nào trên trang này.'
        }));
      }
      return;
    }

    // Bao gồm cả trường hợp đang đọc giữa một ảnh webtoon rất dài.
    let targetImg = null;
    let bestVisibleArea = 0;
    for (const img of images) {
      if (automatic && completedUrls.has(extractBestImageUrl(img))) continue;
      const rect = img.getBoundingClientRect();
      const visibleHeight = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
      const visibleWidth = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
      // Prefetch only nearby images, not the whole chapter (each image costs credits).
      const nearHeight = Math.max(0, Math.min(rect.bottom, window.innerHeight + 200) - Math.max(rect.top, -200));
      const area = visibleHeight * visibleWidth || (automatic ? nearHeight * visibleWidth * 0.001 : 0);
      if (area > bestVisibleArea) {
        bestVisibleArea = area;
        targetImg = img;
      }
    }
    if (!targetImg) {
      if (automatic) return;
      window.ReactNativeWebView?.postMessage(JSON.stringify({type: 'ERROR', message: 'Hãy cuộn đến ảnh truyện cần dịch.'}));
      return;
    }

    // Đánh dấu ảnh đang được dịch để lát nữa render đúng vị trí
    images.forEach(img => img.removeAttribute('data-ctvn-active-target'));
    targetImg.setAttribute('data-ctvn-active-target', 'true');
    const targetId = Date.now().toString(36) + Math.random().toString(36).slice(2);
    pendingTargets.set(targetId, {img: targetImg, url: extractBestImageUrl(targetImg)});
    if (automatic) autoTarget = {id: targetId, url: extractBestImageUrl(targetImg)};

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
      pendingTargets.delete(targetId);
      if (automatic) { autoTarget = null; autoTranslate = false; }
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
        targetId: targetId,
        automatic: Boolean(automatic),
        refererOrigin: window.location.origin,
        pageTitle: document.title || 'Truyện tranh',
        pageUrl: window.location.href
      }));
    }
  };

  // 5. Vẽ đè các khối thoại lên đúng trang truyện
  function fitBubble(bubble, textEl, text) {
    textEl.textContent = String(text || '').normalize('NFC');
    const availableWidth = Math.max(0, bubble.clientWidth - 4);
    const availableHeight = Math.max(0, bubble.clientHeight - 4);
    let fitted = false;
    // Measure the real font and wrapping instead of estimating from box area.
    for (let size = 16; size >= 9; size -= 0.5) {
      bubble.style.setProperty('font-size', size + 'px', 'important');
      if (textEl.scrollWidth <= availableWidth && textEl.scrollHeight <= availableHeight) {
        fitted = true;
        break;
      }
    }
    bubble.dataset.overflow = fitted ? 'false' : 'true';
    if (!fitted) {
      // Full text opens on tap. Never grow the box over neighbouring artwork.
      textEl.textContent = '\u2026';
      bubble.style.setProperty('font-size', Math.min(14, Math.max(1, availableHeight / 1.25)) + 'px', 'important');
    }
  }

  function renderPage(state) {
    const img = state.img;
    if (!img.isConnected) return;
    if (!state.layer || state.layer.parentElement !== overlayRoot) {
      if (state.layer) state.layer.remove();
      state.layer = document.createElement('div');
      state.layer.className = 'ctvn-overlay-layer';
      overlayRoot.appendChild(state.layer);
    }
    const layer = state.layer;
    layer.style.display = showingOriginal ? 'none' : 'block';
    if (showingOriginal) return;

    // Use viewport coordinates; never insert into AMP/reader-owned image wrappers.
    const imgRect = img.getBoundingClientRect();
    const imageScaleX = img.offsetWidth ? imgRect.width / img.offsetWidth : 1;
    const imageScaleY = img.offsetHeight ? imgRect.height / img.offsetHeight : 1;
    const imageStyle = window.getComputedStyle(img);
    const insetLeft = parseFloat(imageStyle.borderLeftWidth) + parseFloat(imageStyle.paddingLeft);
    const insetTop = parseFloat(imageStyle.borderTopWidth) + parseFloat(imageStyle.paddingTop);
    const dispW = (img.clientWidth - parseFloat(imageStyle.paddingLeft) - parseFloat(imageStyle.paddingRight)) * imageScaleX;
    const dispH = (img.clientHeight - parseFloat(imageStyle.paddingTop) - parseFloat(imageStyle.paddingBottom)) * imageScaleY;
    // Uploaded source may have a different resolution from the displayed thumbnail.
    const natW = state.imageWidth || img.naturalWidth;
    const natH = state.imageHeight || img.naturalHeight;
    if (!(natW > 0 && natH > 0 && dispW > 0 && dispH > 0)) return;
    layer.style.left = (imgRect.left + insetLeft * imageScaleX) + 'px';
    layer.style.top = (imgRect.top + insetTop * imageScaleY) + 'px';
    layer.style.width = dispW + 'px';
    layer.style.height = dispH + 'px';
    const layoutKey = dispW + ':' + dispH;
    if (state.layoutKey === layoutKey) return;
    state.layoutKey = layoutKey;
    layer.replaceChildren();

    state.blocks.forEach(function(blk) {
      if (!Array.isArray(blk.bbox) || blk.bbox.length !== 4 || !blk.bbox.every(Number.isFinite)) return;
      const [x1, y1, x2, y2] = blk.bbox;
      const left = Math.max(0, Math.min(natW, x1)) * dispW / natW;
      const top = Math.max(0, Math.min(natH, y1)) * dispH / natH;
      const right = Math.max(0, Math.min(natW, x2)) * dispW / natW;
      const bottom = Math.max(0, Math.min(natH, y2)) * dispH / natH;
      if (right <= left || bottom <= top) return;
      const bubble = document.createElement('div');
      bubble.className = 'ctvn-bubble-box';
      bubble.dataset.blockId = String(blk.id);
      bubble.setAttribute('role', 'button');
      bubble.setAttribute('aria-label', 'Ch\u1ea1m \u0111\u1ec3 \u0111\u1ecdc to\u00e0n b\u1ed9 b\u1ea3n d\u1ecbch');
      bubble.tabIndex = 0;
      bubble.style.left = left + 'px';
      bubble.style.top = top + 'px';
      bubble.style.width = (right - left) + 'px';
      bubble.style.height = (bottom - top) + 'px';
      const textEl = document.createElement('span');
      textEl.className = 'ctvn-bubble-text';
      bubble.appendChild(textEl);
      layer.appendChild(bubble);
      fitBubble(bubble, textEl, blk.translation || blk.source_text);
      const openDetail = function(e) {
        e.preventDefault();
        e.stopPropagation();
        window.ReactNativeWebView?.postMessage(JSON.stringify({
          type: 'SHOW_TRANSLATION_DETAIL',
          translation: blk.translation || '',
          sourceText: blk.source_text || ''
        }));
      };
      bubble.onclick = openDetail;
      bubble.onkeydown = function(e) { if (e.key === 'Enter' || e.key === ' ') openDetail(e); };
    });
  }

  function scheduleLayout() {
    scheduleAutoTranslation();
    if (layoutFrame) return;
    layoutFrame = requestAnimationFrame(function() {
      layoutFrame = 0;
      renderedPages.forEach(function(state, img) {
        if (!img.isConnected) {
          state.layer?.remove();
          resizeObserver?.unobserve(img);
          renderedPages.delete(img);
        } else {
          renderPage(state);
        }
      });
    });
  }
  const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(scheduleLayout) : null;
  window.addEventListener('scroll', scheduleLayout, {passive: true, capture: true});
  window.addEventListener('resize', scheduleLayout);
  window.addEventListener('orientationchange', scheduleLayout);
  // Lazy-loaded images above this one can change its offset inside a shared parent.
  document.addEventListener('load', scheduleLayout, true);
  if (document.fonts) {
    const refitFonts = function() {
      renderedPages.forEach(state => { state.layoutKey = null; });
      scheduleLayout();
    };
    document.fonts.ready.then(refitFonts);
    document.fonts.addEventListener('loadingdone', refitFonts);
  }

  window.__setTranslationOriginal = function(value) {
    showingOriginal = Boolean(value);
    renderedPages.forEach(renderPage);
  };

  function scheduleAutoTranslation() {
    if (!autoTranslate || autoTarget || autoTimer) return;
    autoTimer = setTimeout(function() {
      autoTimer = 0;
      window.__triggerTranslateActivePage(true);
    }, 250);
  }

  window.__setAutoTranslate = function(value, context) {
    if (value && context && context !== translationContext) {
      completedUrls.clear();
      translationContext = context;
    }
    autoTranslate = Boolean(value);
    if (!autoTranslate && autoTimer) { clearTimeout(autoTimer); autoTimer = 0; }
    scheduleAutoTranslation();
  };

  window.__releaseTranslationTarget = function(targetId, success) {
    pendingTargets.delete(targetId);
    if (autoTarget?.id === targetId) {
      if (success) completedUrls.add(autoTarget.url);
      else autoTranslate = false;
      autoTarget = null;
      scheduleAutoTranslation();
    }
  };

  window.__renderRealTranslatedBlocks = function(blocks, showOriginal, metadata, targetId) {
    const pending = targetId ? pendingTargets.get(targetId) : null;
    let img = pending?.img || (!targetId && document.querySelector('img[data-ctvn-active-target="true"]'));
    // Rebind only to the requested URL in this document, never an arbitrary image.
    if (pending && (!img?.isConnected || extractBestImageUrl(img) !== pending.url)) {
      img = findComicImages().find(candidate => extractBestImageUrl(candidate) === pending.url);
    }
    if (targetId) pendingTargets.delete(targetId);
    const report = function(count, message) {
      window.ReactNativeWebView?.postMessage(JSON.stringify({
        type: 'TRANSLATION_RENDER_RESULT', targetId: targetId, count: count,
        showingOriginal: showingOriginal, message: message || ''
      }));
    };
    if (!img || !img.isConnected) {
      report(0, 'Ảnh cần dịch đã thay đổi. Hãy bấm Dịch trang lại.');
      return;
    }
    const state = renderedPages.get(img) || {img: img, layer: null};
    state.blocks = Array.isArray(blocks) ? blocks : [];
    state.layoutKey = null;
    state.imageWidth = Number(metadata?.image_width) || 0;
    state.imageHeight = Number(metadata?.image_height) || 0;
    renderedPages.set(img, state);
    resizeObserver?.observe(img);
    if (img.parentElement) resizeObserver?.observe(img.parentElement);
    showingOriginal = Boolean(showOriginal);
    try {
      renderPage(state);
      const count = state.layer?.querySelectorAll('.ctvn-bubble-box').length || 0;
      report(count, count || !state.blocks.length || showingOriginal ? '' : 'Không vẽ được khung dịch. Hãy đợi ảnh tải xong rồi thử lại.');
    } catch (error) {
      report(0, 'Lỗi hiển thị khung dịch: ' + String(error.message || error));
    }
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
