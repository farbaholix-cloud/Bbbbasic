#!/bin/bash
# Farbaholix Video Converter — сборка .app и .dmg
# Запускай на Mac: bash build.sh

set -e
cd "$(dirname "$0")"

echo "📦 Устанавливаем зависимости..."
pip3 install --quiet customtkinter pyinstaller

echo "🔨 Собираем .app..."
pyinstaller \
  --windowed \
  --onedir \
  --name "Farbaholix Video Converter" \
  --collect-all customtkinter \
  --hidden-import tkinterdnd2 \
  farbaholix_converter.py

APP="dist/Farbaholix Video Converter.app"

if [ ! -d "$APP" ]; then
  echo "❌ .app не создан, что-то пошло не так"
  exit 1
fi

echo "💿 Создаём DMG..."
DMG="Farbaholix_Video_Converter.dmg"
rm -f "$DMG"

hdiutil create \
  -volname "Farbaholix Video Converter" \
  -srcfolder "$APP" \
  -ov -format UDZO \
  "$DMG"

echo ""
echo "✅ Готово: $(pwd)/$DMG"
echo "   Открой DMG и перетащи приложение в /Applications"
open "$(pwd)"
