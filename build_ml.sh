#!/bin/bash
echo "Building C ML extension..."
python3 setup_ml_core.py build_ext --inplace 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ C extension built successfully"
else
    echo "⚠️  C extension build failed - Python fallback will be used"
fi
