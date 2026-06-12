/* global ScheduleParser, ScheduleRenderer, ScheduleOCR */

(function () {
  'use strict';

  const STORAGE_KEY = 'schedule_data_v1';
  const { parseSchedule } = ScheduleParser;
  const { renderSchedule } = ScheduleRenderer;

  const uploadScreen   = document.getElementById('upload-screen');
  const viewScreen     = document.getElementById('view-screen');
  const clearBtn       = document.getElementById('clear-btn');
  const errorBox       = document.getElementById('error-box');
  const scheduleContainer = document.getElementById('schedule-container');

  const tabs   = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.tab-panel');

  const photoBtn         = document.getElementById('photo-btn');
  const photoInput       = document.getElementById('photo-input');
  const photoZone        = document.getElementById('photo-zone');
  const photoPreviewWrap = document.getElementById('photo-preview-wrap');
  const photoPreview     = document.getElementById('photo-preview');
  const photoChange      = document.getElementById('photo-change');
  const ocrBtn           = document.getElementById('ocr-btn');
  const ocrProgress      = document.getElementById('ocr-progress');
  const ocrBarFill       = document.getElementById('ocr-bar-fill');
  const ocrStatus        = document.getElementById('ocr-status');
  const ocrResultWrap    = document.getElementById('ocr-result-wrap');
  const ocrResultText    = document.getElementById('ocr-result-text');
  const ocrEditToggle    = document.getElementById('ocr-edit-toggle');
  const ocrParseBtn      = document.getElementById('ocr-parse-btn');

  const dropZone   = document.getElementById('drop-zone');
  const uploadBtn  = document.getElementById('upload-btn');
  const fileInput  = document.getElementById('file-input');

  const pasteArea  = document.getElementById('paste-area');
  const parseBtn   = document.getElementById('parse-btn');
  const charCount  = document.getElementById('char-count');

  function setViewMode(active) {
    uploadScreen.classList.toggle('hidden', active);
    viewScreen.classList.toggle('hidden', !active);
    clearBtn.style.display = active ? 'flex' : 'none';
  }

  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      parsed.shifts = parsed.shifts.map(s => ({ ...s, date: s.date ? new Date(s.date) : null }));
      setViewMode(true);
      renderSchedule(parsed, scheduleContainer);
    } catch (e) { localStorage.removeItem(STORAGE_KEY); }
  }

  clearBtn.addEventListener('click', () => {
    localStorage.removeItem(STORAGE_KEY);
    setViewMode(false);
    pasteArea.value = '';
    charCount.textContent = '';
    resetPhotoUI();
    hideError();
  });

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.add('hidden'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.remove('hidden');
      hideError();
    });
  });

  photoBtn.addEventListener('click', () => photoInput.click());
  photoChange.addEventListener('click', () => photoInput.click());

  photoInput.addEventListener('change', () => {
    const file = photoInput.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    photoPreview.onload = () => URL.revokeObjectURL(url);
    photoPreview.src = url;
    photoZone.classList.add('hidden');
    photoPreviewWrap.classList.remove('hidden');
    ocrProgress.classList.add('hidden');
    ocrResultWrap.classList.add('hidden');
    hideError();
  });

  ocrBtn.addEventListener('click', async () => {
    if (!photoPreview.src) return;
    hideError();
    ocrBtn.disabled = true;
    ocrProgress.classList.remove('hidden');
    ocrResultWrap.classList.add('hidden');
    setOcrProgress(0, 'Загружаю модуль...');
    try {
      const text = await ScheduleOCR.recognizeScheduleImage(photoPreview, (pct, msg) => setOcrProgress(pct, msg));
      setOcrProgress(100, 'Готово!');
      ocrResultText.value = text;
      ocrResultWrap.classList.remove('hidden');
      processText(text);
    } catch (e) {
      showError('Ошибка распознавания: ' + e.message);
      ocrProgress.classList.add('hidden');
    } finally {
      ocrBtn.disabled = false;
    }
  });

  ocrEditToggle.addEventListener('click', () => {
    const visible = !ocrResultText.classList.contains('hidden');
    ocrResultText.classList.toggle('hidden', visible);
    ocrEditToggle.textContent = visible ? 'Показать текст' : 'Скрыть текст';
  });

  ocrParseBtn.addEventListener('click', () => processText(ocrResultText.value));

  function setOcrProgress(pct, msg) {
    ocrBarFill.style.width = pct + '%';
    ocrStatus.textContent = msg || '';
  }

  function resetPhotoUI() {
    photoZone.classList.remove('hidden');
    photoPreviewWrap.classList.add('hidden');
    ocrProgress.classList.add('hidden');
    ocrResultWrap.classList.add('hidden');
    photoPreview.src = '';
    ocrResultText.value = '';
    ocrBtn.disabled = false;
  }

  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) readTextFile(file);
  });
  uploadBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) readTextFile(fileInput.files[0]); });

  function readTextFile(file) {
    const reader = new FileReader();
    reader.onload = e => processText(e.target.result);
    reader.onerror = () => showError('Не удалось прочитать файл');
    reader.readAsText(file, 'UTF-8');
  }

  pasteArea.addEventListener('input', () => {
    charCount.textContent = pasteArea.value.length > 0 ? pasteArea.value.length + ' символов' : '';
    if (pasteArea.value.length > 0) hideError();
  });
  parseBtn.addEventListener('click', () => {
    const text = pasteArea.value.trim();
    if (!text) { showError('Вставьте данные расписания'); return; }
    processText(text);
  });

  function processText(text) {
    hideError();
    if (!text || !text.trim()) { showError('Текст пустой — попробуй снова'); return; }
    try {
      const data = parseSchedule(text);
      if (!data.shifts || data.shifts.length === 0) {
        showError('Не удалось распознать расписание. Проверьте качество фото или попробуйте вставить текст вручную.');
        return;
      }
      const toSave = { ...data, shifts: data.shifts.map(s => ({ ...s, date: s.date ? s.date.toISOString() : null })) };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
      setViewMode(true);
      renderSchedule(data, scheduleContainer);
    } catch (e) {
      showError('Ошибка: ' + e.message);
    }
  }

  function showError(msg) { errorBox.textContent = msg; errorBox.classList.remove('hidden'); }
  function hideError()    { errorBox.classList.add('hidden'); }

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  let deferredPrompt = null;
  const installBanner = document.getElementById('install-banner');
  const installBtn    = document.getElementById('install-btn');
  const dismissBtn    = document.getElementById('dismiss-install');

  window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault(); deferredPrompt = e;
    if (installBanner) installBanner.classList.remove('hidden');
  });
  if (installBtn) installBtn.addEventListener('click', () => {
    if (deferredPrompt) { deferredPrompt.prompt(); deferredPrompt = null; }
    if (installBanner) installBanner.classList.add('hidden');
  });
  if (dismissBtn) dismissBtn.addEventListener('click', () => { if (installBanner) installBanner.classList.add('hidden'); });
})();