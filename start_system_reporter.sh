#!/bin/bash
# =====================================================================
# SuggestInvest • System Reporting & Resource Monitor Daemon (Cloud VPS)
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Aktivace virtuálního prostředí (pokud existuje)
if [ -d "$SCRIPT_DIR/venv" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

echo "====================================================================="
echo "📊 SuggestInvest • System Reporting Daemon (Cloud VPS)"
echo "====================================================================="
echo "Adresář:    $SCRIPT_DIR"
echo "Python:     $(which python3 || which python)"
echo "Ukládání:   data/system_report.json"
echo "Log:        logs/system_reporter.log"
echo "====================================================================="

# Instalace závislostí pokud chybí
python3 -c "import psutil" 2>/dev/null || {
    echo "⚠️ psutil není nainstalován, instaluji přes pip..."
    pip install psutil
}

# Spuštění s předanými argumenty nebo výchozím intervalem 10s
exec python3 system_reporter.py "$@"
