// OCR module using Tesseract.js (loaded lazily from CDN)

const TESSERACT_CDN = 'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js';

function loadTesseract() {
  if (window.Tesseract) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = TESSERACT_CDN;
    s.onload = resolve;
    s.onerror = () => reject(new Error('Не удалось загрузить модуль распознавания'));
    document.head.appendChild(s);
  });
}

function preprocessImage(imgEl) {
  const canvas = document.createElement('canvas');
  const MAX = 2400;
  let w = imgEl.naturalWidth;
  let h = imgEl.naturalHeight;
  if (w > MAX || h > MAX) {
    const scale = MAX / Math.max(w, h);
    w = Math.round(w * scale);
    h = Math.round(h * scale);
  }
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(imgEl, 0, 0, w, h);
  const imageData = ctx.getImageData(0, 0, w, h);
  const d = imageData.data;
  for (let i = 0; i < d.length; i += 4) {
    const gray = 0.299 * d[i] + 0.587 * d[i+1] + 0.114 * d[i+2];
    const c = Math.min(255, Math.max(0, (gray - 128) * 1.4 + 128));
    d[i] = d[i+1] = d[i+2] = c;
  }
  ctx.putImageData(imageData, 0, 0);
  return canvas;
}

async function recognizeScheduleImage(imgEl, onProgress) {
  await loadTesseract();
  const canvas = preprocessImage(imgEl);
  const { data: { text } } = await window.Tesseract.recognize(
    canvas,
    'deu+eng',
    {
      logger: m => {
        if (!onProgress) return;
        if (m.status === 'recognizing text') onProgress(Math.round(m.progress * 100), 'Читаю текст...');
        else if (m.status === 'loading tesseract core') onProgress(5, 'Загружаю модуль...');
        else if (m.status === 'initializing tesseract') onProgress(10, 'Инициализация...');
        else if (m.status === 'loading language traineddata') onProgress(20, 'Загружаю языковой пакет...');
        else if (m.status === 'initializing api') onProgress(30, 'Запускаю распознавание...');
      }
    }
  );
  return text;
}

window.ScheduleOCR = { recognizeScheduleImage };