/* PDF reader: page navigation and zoom via pdf.js (vendored locally). */
(function () {
  'use strict';

  var stage = document.querySelector('.reader');
  if (!stage || typeof pdfjsLib === 'undefined') return;

  var pdfUrl = stage.dataset.pdfUrl;
  var canvas = document.getElementById('pdf-canvas');
  var ctx = canvas.getContext('2d');

  var loadingEl = document.getElementById('reader-loading');
  var errorEl = document.getElementById('reader-error');
  var errorMsg = document.getElementById('reader-error-msg');
  var pageInput = document.getElementById('page-input');
  var pageCountEl = document.getElementById('page-count');
  var zoomLevelEl = document.getElementById('zoom-level');

  pdfjsLib.GlobalWorkerOptions.workerSrc =
    (document.querySelector('script[src*="pdf.min.js"]').src || '/static/vendor/pdfjs/pdf.min.js')
      .replace('pdf.min.js', 'pdf.worker.min.js');

  var pdfDoc = null;
  var pageNum = 1;
  var pageRendering = false;
  var pendingPage = null;
  var scale = 1.0;
  var fitMode = false;
  var MIN_SCALE = 0.25;
  var MAX_SCALE = 4.0;

  function setLoading(on) {
    loadingEl.hidden = !on;
  }

  function showError(message) {
    setLoading(false);
    canvas.hidden = true;
    errorEl.hidden = false;
    errorMsg.textContent = message;
  }

  function updateControls() {
    pageInput.value = String(pageNum);
    pageInput.max = String(pdfDoc ? pdfDoc.numPages : 1);
    pageCountEl.textContent = pdfDoc ? String(pdfDoc.numPages) : '–';
    zoomLevelEl.textContent = Math.round(scale * 100) + '%';
    document.getElementById('btn-prev').disabled = pageNum <= 1;
    document.getElementById('btn-next').disabled = !pdfDoc || pageNum >= pdfDoc.numPages;
    document.getElementById('btn-prev-m').disabled = pageNum <= 1;
    document.getElementById('btn-next-m').disabled = !pdfDoc || pageNum >= pdfDoc.numPages;
  }

  function computeFitScale(page) {
    var viewport = page.getViewport({ scale: 1.0 });
    var available = Math.min(stage.clientWidth - 32, 1000);
    return Math.max(MIN_SCALE, Math.min(MAX_SCALE, available / viewport.width));
  }

  function renderPage(num) {
    if (!pdfDoc) return;
    if (pageRendering) {
      pendingPage = num;
      return;
    }
    pageRendering = true;
    setLoading(false);
    errorEl.hidden = true;

    pdfDoc.getPage(num).then(function (page) {
      if (fitMode) {
        scale = computeFitScale(page);
      }
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var viewport = page.getViewport({ scale: scale });
      var renderViewport = page.getViewport({ scale: scale * dpr });

      canvas.width = Math.floor(renderViewport.width);
      canvas.height = Math.floor(renderViewport.height);
      canvas.style.width = Math.floor(viewport.width) + 'px';
      canvas.style.height = Math.floor(viewport.height) + 'px';
      canvas.hidden = false;

      var task = canvas.getContext('2d');
      task.setTransform(1, 0, 0, 1, 0, 0);

      return page.render({
        canvasContext: task,
        viewport: renderViewport
      }).promise;
    }).then(function () {
      pageRendering = false;
      updateControls();
      if (pendingPage !== null && pendingPage !== pageNum) {
        var next = pendingPage;
        pendingPage = null;
        pageNum = next;
        renderPage(pageNum);
      } else {
        pendingPage = null;
      }
    }).catch(function (err) {
      pageRendering = false;
      console.error(err);
      showError('The PDF failed to render: ' + (err && err.message ? err.message : 'unknown error'));
    });
  }

  function queueRender(num) {
    if (!pdfDoc) return;
    num = Math.max(1, Math.min(pdfDoc.numPages, num));
    pageNum = num;
    updateControls();
    renderPage(num);
  }

  function goTo(num) { queueRender(num); }
  function next() { goTo(pageNum + 1); }
  function prev() { goTo(pageNum - 1); }

  function setZoom(nextScale) {
    fitMode = false;
    scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, nextScale));
    renderPage(pageNum);
    updateControls();
  }

  function fitWidth() {
    fitMode = true;
    if (!pdfDoc) return;
    pdfDoc.getPage(pageNum).then(function (page) {
      scale = computeFitScale(page);
      renderPage(pageNum);
      updateControls();
    });
  }

  // --- wire up controls -------------------------------------------------
  document.getElementById('btn-prev').addEventListener('click', prev);
  document.getElementById('btn-next').addEventListener('click', next);
  document.getElementById('btn-prev-m').addEventListener('click', prev);
  document.getElementById('btn-next-m').addEventListener('click', next);

  pageInput.addEventListener('change', function () {
    var value = parseInt(pageInput.value, 10);
    if (isNaN(value)) { updateControls(); return; }
    goTo(value);
  });
  pageInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      var value = parseInt(pageInput.value, 10);
      if (!isNaN(value)) goTo(value);
    }
  });

  document.getElementById('btn-zoom-in').addEventListener('click', function () {
    setZoom(scale * 1.2);
  });
  document.getElementById('btn-zoom-out').addEventListener('click', function () {
    setZoom(scale / 1.2);
  });
  document.getElementById('btn-fit').addEventListener('click', fitWidth);

  document.addEventListener('keydown', function (event) {
    var tag = (event.target && event.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); next(); }
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); prev(); }
    if (event.key === '+' || event.key === '=') { setZoom(scale * 1.2); }
    if (event.key === '-') { setZoom(scale / 1.2); }
  });

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!fitMode) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { fitWidth(); }, 180);
  });

  document.getElementById('btn-retry').addEventListener('click', function () {
    errorEl.hidden = true;
    load();
  });

  // --- load the document ------------------------------------------------
  function load() {
    setLoading(true);
    errorEl.hidden = true;
    pdfDoc = null;

    pdfjsLib.getDocument({
      url: pdfUrl,
      // same-origin request; admin session cookie is sent automatically
      withCredentials: true
    }).promise.then(function (doc) {
      if (!doc.numPages) {
        showError('This PDF appears to have no pages.');
        return;
      }
      pdfDoc = doc;
      pageNum = 1;
      fitMode = true;
      updateControls();
      renderPage(pageNum);
    }).catch(function (err) {
      console.error(err);
      var message = 'The PDF could not be loaded.';
      if (err && err.name === 'InvalidPDFException') {
        message = 'The stored file is not a readable PDF.';
      } else if (err && err.status === 404) {
        message = 'The file was not found on the server.';
      }
      showError(message);
    });
  }

  load();
})();
