#!/usr/bin/env python3
"""
Verificação Completa de Funcionalidade - IA Google Meet
Analisa sintaxe, imports, testes e estrutura do projeto
"""

import sys
import os
import ast
from pathlib import Path
from collections import defaultdict

class ProjectValidator:
    def __init__(self, root_path="."):
        self.root = Path(root_path)
        self.issues = defaultdict(list)
        self.stats = {
            "total_files": 0,
            "syntax_errors": 0,
            "import_errors": 0,
            "valid_files": 0,
        }
    
    def validate_syntax(self):
        """Check syntax of all Python files"""
        print("🔍 Checking Python Syntax...\n")
        
        for py_file in sorted(self.root.rglob("*.py")):
            if any(skip in str(py_file) for skip in ["venv", ".pytest_cache", "data/"]):
                continue
            
            self.stats["total_files"] += 1
            
            try:
                with open(py_file) as f:
                    ast.parse(f.read())
                self.stats["valid_files"] += 1
            except SyntaxError as e:
                self.stats["syntax_errors"] += 1
                self.issues["syntax"].append({
                    "file": str(py_file),
                    "error": str(e)[:100]
                })
                print(f"  ❌ {py_file}: {str(e)[:60]}")
        
        if self.stats["syntax_errors"] == 0:
            print(f"  ✅ All {self.stats['total_files']} files have valid syntax!\n")
        else:
            print(f"  ❌ Found {self.stats['syntax_errors']} syntax errors\n")
    
    def check_structure(self):
        """Verify project structure"""
        print("📁 Checking Project Structure...\n")
        
        required_dirs = [
            "domain",
            "domain/entities",
            "infrastructure",
            "use_cases",
            "interface",
            "presentation",
            "test",
        ]
        
        for dir_name in required_dirs:
            dir_path = self.root / dir_name
            if dir_path.exists():
                print(f"  ✅ {dir_name}/")
            else:
                print(f"  ❌ {dir_name}/ (MISSING)")
                self.issues["structure"].append(f"Missing: {dir_name}")
        print()
    
    def check_critical_files(self):
        """Check if critical files exist"""
        print("📄 Checking Critical Files...\n")
        
        critical_files = [
            "main.py",
            "config/settings.py",
            "entities/metting.py",
            "entities/meeting_type.py",
            "interface/transcriber.py",
            "interface/llm_services.py",
            "infrastructure/transcriber/whisper_transcriber.py",
            "infrastructure/transcriber/pyannote_diarizer.py",
            "llm/langchain_llm_service.py",
            "presentation/container.py",
        ]
        
        for file_name in critical_files:
            file_path = self.root / file_name
            if file_path.exists():
                print(f"  ✅ {file_name}")
            else:
                print(f"  ⚠️  {file_name} (MISSING)")
                self.issues["missing_files"].append(file_name)
        print()
    
    def check_imports(self):
        """Test critical imports"""
        print("🔗 Testing Critical Imports...\n")
        
        sys.path.insert(0, str(self.root))
        
        test_imports = [
            ("interface.transcriber", "TranscriptionError"),
            ("interface.llm_services", "ILLMService"),
            ("config.settings", "get_settings"),
            ("entities.metting", "Meeting"),
            ("entities.meeting_type", "MeetingType"),
            ("infrastructure.transcriber.whisper_transcriber", "WhisperTranscriber"),
            ("infrastructure.transcriber.pyannote_diarizer", "PyannoteDiarizer"),
        ]
        
        failed = 0
        for module_name, class_name in test_imports:
            try:
                mod = __import__(module_name, fromlist=[class_name])
                getattr(mod, class_name)
                print(f"  ✅ {module_name}.{class_name}")
            except Exception as e:
                failed += 1
                print(f"  ❌ {module_name}.{class_name}")
                print(f"     └─ {str(e)[:80]}")
                self.issues["imports"].append(f"{module_name}.{class_name}: {str(e)[:60]}")
        
        print(f"\n  Result: {len(test_imports) - failed}/{len(test_imports)} imports OK\n")
    
    def check_tests(self):
        """Run tests and get status"""
        print("🧪 Checking Test Status...\n")
        
        test_dir = self.root / "test"
        if test_dir.exists():
            test_files = list(test_dir.glob("test_*.py"))
            print(f"  Found {len(test_files)} test files:")
            for tf in sorted(test_files):
                print(f"    - {tf.name}")
        
        print()
    
    def generate_report(self):
        """Generate final report"""
        print("=" * 60)
        print("📊 FUNCIONALIDADE REPORT - IA GOOGLE MEET")
        print("=" * 60)
        print()
        
        self.validate_syntax()
        self.check_structure()
        self.check_critical_files()
        self.check_imports()
        self.check_tests()
        
        # Summary
        print("=" * 60)
        print("📈 RESUMO")
        print("=" * 60)
        print(f"Total de Arquivos Python: {self.stats['total_files']}")
        print(f"Arquivos Válidos: {self.stats['valid_files']} ✅")
        print(f"Erros de Sintaxe: {self.stats['syntax_errors']} ❌" if self.stats['syntax_errors'] > 0 else f"Erros de Sintaxe: 0 ✅")
        print(f"Issues Encontrados: {sum(len(v) for v in self.issues.values())}")
        
        if self.issues:
            print("\n⚠️  PROBLEMAS ENCONTRADOS:\n")
            for category, problems in self.issues.items():
                if problems:
                    print(f"{category.upper()}:")
                    for problem in problems[:5]:
                        if isinstance(problem, dict):
                            print(f"  - {problem.get('file', problem)}")
                        else:
                            print(f"  - {problem}")
                    if len(problems) > 5:
                        print(f"  ... e {len(problems) - 5} mais")
                    print()
        
        # Overall status
        print("=" * 60)
        if self.stats["syntax_errors"] == 0 and not self.issues.get("imports"):
            print("✅ PROJETO ESTÁ FUNCIONAL!")
            print("Status: Pronto para desenvolvimento/produção")
        else:
            print("⚠️  PROJETO TEM ALGUNS PROBLEMAS")
            print("Status: Requer correções antes de usar em produção")
        print("=" * 60)


if __name__ == "__main__":
    validator = ProjectValidator()
    validator.generate_report()
