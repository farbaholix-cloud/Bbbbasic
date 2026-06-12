/* global ScheduleParser, ScheduleRenderer */

(function () {
  'use strict';

  const STORAGE_KEY = 'schedule_data_v1';
  const { parseSchedule } = ScheduleParser;
  const { renderSchedule } = ScheduleRenderer;

  let currentData = null;

  const uploadScreen = document.getElementById('upload-screen');
  const viewScreen = document.getElementById('view-screen');
  const fileInput = document.getElementById('file-input');
  const pasteArea = document.getElementById('paste-area');
  const dropZone = document.getElementById('drop-zone');
  const parseBtn = document.getElementById('parse-btn');
  const clearBtn = document.getElementById('clear-btn');
  const uploadBtn = document.getElementById('upload-btn');
  const scheduleContainer = document.getElementById('schedule-container');
  const errorBox = document.getElementById('error-box');
  const charCount = document.getElementById('char-count');

  function setViewMode(active) {
    uploadScreen.classList.toggle('hidden', active);
    viewScreen.classList.toggle('hidden', !active);
    clearBtn.style.display = active ? 'flex' : 'none';
  }

  // Restore saved data
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      parsed.shifts = parsed.shifts.map(s => ({ ...s, date: s.date ? new Date(s.date) : null }));
      currentData = parsed;
      setViewMode(true);
      renderSchedule(currentData, scheduleContainer);
    } catch (e) {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  // Drag & drop
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) readFile(file);
  });

  uploadBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) readFile(fileInput.files[0]);
  });

  pasteArea.addEventListener('input', () => {
    const len = pasteArea.value.length;
    charCount.textContent = len > 0 ? len + ' символов' : '';
    if (len > 0) hideError();
  });

  parseBtn.addEventListener('click', () => {
    const text = pasteArea.value.trim();
    if (!text) { showError('Вставьте данные расписания в поле выше'); return; }
    processText(text);
  });

  clearBtn.addEventListener('click', () => {
    localStorage.removeItem(STORAGE_KEY);
    currentData = null;
    setViewMode(false);
    pasteArea.value = '';
    charCount.textContent = '';
    hideError();
  });

  function readFile(file) {
    const reader = new FileReader();
    reader.onload = e => {
      const text = e.target.result;
      pasteArea.value = text;
      charCount.textContent = text.length + ' символов';
      processText(text);
    };
    reader.onerror = () => showError('Не удалось прочитать файл');
    reader.readAsText(file, 'UTF-8');
  }

  function processText(text) {
    hideError();
    try {
      const data = parseSchedule(text);
      if (!data.shifts || data.shifts.length === 0) {
        showError('Не удалось распознать расписание. Убедитесь что данные содержат столбцы: день, начало, конец смены.');
        return;
      }
      currentData = data;
      const toSave = {
        ...data,
        shifts: data.shifts.map(s => ({ ...s, date: s.date ? s.date.toISOString() : null }))
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
      setViewMode(true);
      renderSchedule(data, scheduleContainer);
    } catch (e) {
      showError('Ошибка разбора: ' + e.message);
    }
  }

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.classList.remove('hidden');
  }

  function hideError() {
    errorBox.classList.add('hidden');
  }

  // Register SW
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }

  // Install prompt
  let deferredPrompt = null;
  const installBanner = document.getElementById('install-banner');
  const installBtn = document.getElementById('install-btn');
  const dismissBtn = document.getElementById('dismiss-install');

  window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    deferredPrompt = e;
    if (installBanner) installBanner.classList.remove('hidden');
  });

  if (installBtn) installBtn.addEventListener('click', () => {
    if (deferredPrompt) { deferredPrompt.prompt(); deferredPrompt = null; }
    if (installBanner) installBanner.classList.add('hidden');
  });

  if (dismissBtn) dismissBtn.addEventListener('click', () => {
    if (installBanner) installBanner.classList.add('hidden');
  });
})();
