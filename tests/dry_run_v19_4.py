import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.parameter_extractor import normalize_path, clean_name_string

def test_fixes():
    print("--- Wiqo v19.4 Dry Run Test ---")
    
    test_cases = [
        # Path Normalization
        ("/Desktop/test", "~/Desktop/test"),
        ("masaüstü/rapor", "~/Desktop/rapor"),
        ("Masaüstü Klasör", "~/Desktop/Klasör"),
        
        # Name Cleaning
        ("test adında", "test"),
        ("proje isimli", "proje"),
        ("rapor adlı dosya", "rapor adlı dosya"), # Only cleaning adında/isimli/adlı if suffix-like
        ("Yeni Klasör", "Klasör"),
    ]
    
    print("\n[Path Normalization]")
    for inp, expected in test_cases[:3]:
        result = normalize_path(inp)
        status = "✅" if result == expected else "❌"
        print(f"{status} {inp} -> {result} (Expected: {expected})")
        
    print("\n[Name Cleaning]")
    for inp, expected in test_cases[3:]:
        result = clean_name_string(inp)
        status = "✅" if result == expected else "❌"
        print(f"{status} {inp} -> {result} (Expected: {expected})")

    # Specific failing case simulation
    print("\n[Failing Case Simulation]")
    # Input: "masaüstüne test adında klasör oluştur"
    # LLM might extract: action='create_folder', params={'path': '/Desktop/test adi klasörü'} or similar
    
    # Simulation 1: Wrong path from LLM
    llm_path = "/Desktop/test adi klasörü"
    normalized = normalize_path(llm_path)
    cleaned = clean_name_string(normalized)
    print(f"Original: {llm_path}")
    print(f"Normalized & Cleaned: {cleaned}")
    if cleaned == "~/Desktop/test":
         print("✅ Fixed path and name!")

if __name__ == "__main__":
    test_fixes()
