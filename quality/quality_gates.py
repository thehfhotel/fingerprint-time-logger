"""
Quality Gates and Automation Framework
Comprehensive code quality validation with automated checks and reporting
"""
import os
import subprocess
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod

class QualityLevel(Enum):
    """Quality assessment levels"""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    NEEDS_IMPROVEMENT = "needs_improvement"
    CRITICAL = "critical"

@dataclass
class QualityMetric:
    """Individual quality metric result"""
    name: str
    value: float
    threshold: float
    level: QualityLevel
    details: str
    suggestions: List[str]

@dataclass
class QualityReport:
    """Complete quality assessment report"""
    timestamp: str
    overall_score: float
    overall_level: QualityLevel
    metrics: List[QualityMetric]
    passed_gates: List[str]
    failed_gates: List[str]
    execution_time: float

class QualityGate(ABC):
    """Abstract base class for quality gates"""

    def __init__(self, name: str, threshold: float, weight: float = 1.0):
        self.name = name
        self.threshold = threshold
        self.weight = weight

    @abstractmethod
    def check(self, project_root: Path) -> QualityMetric:
        """Execute quality check and return metric"""
        pass

    def _determine_level(self, value: float, threshold: float) -> QualityLevel:
        """Determine quality level based on value and threshold"""
        if value >= threshold + 15:
            return QualityLevel.EXCELLENT
        elif value >= threshold + 5:
            return QualityLevel.GOOD
        elif value >= threshold:
            return QualityLevel.ACCEPTABLE
        elif value >= threshold - 10:
            return QualityLevel.NEEDS_IMPROVEMENT
        else:
            return QualityLevel.CRITICAL

class CodeCoverageGate(QualityGate):
    """Code coverage quality gate"""

    def __init__(self, threshold: float = 85.0):
        super().__init__("Code Coverage", threshold)

    def check(self, project_root: Path) -> QualityMetric:
        """Check code coverage percentage"""
        coverage_file = project_root / "coverage.xml"

        if not coverage_file.exists():
            return QualityMetric(
                name=self.name,
                value=0.0,
                threshold=self.threshold,
                level=QualityLevel.CRITICAL,
                details="Coverage report not found",
                suggestions=["Run pytest with --cov flag to generate coverage"]
            )

        try:
            tree = ET.parse(coverage_file)
            root = tree.getroot()
            coverage_rate = float(root.attrib.get('line-rate', 0)) * 100

            level = self._determine_level(coverage_rate, self.threshold)

            suggestions = []
            if level in [QualityLevel.NEEDS_IMPROVEMENT, QualityLevel.CRITICAL]:
                suggestions = [
                    "Add unit tests for uncovered code paths",
                    "Review excluded files in .coveragerc",
                    "Consider integration tests for complex workflows"
                ]

            return QualityMetric(
                name=self.name,
                value=coverage_rate,
                threshold=self.threshold,
                level=level,
                details=f"Line coverage: {coverage_rate:.1f}%",
                suggestions=suggestions
            )

        except Exception as e:
            return QualityMetric(
                name=self.name,
                value=0.0,
                threshold=self.threshold,
                level=QualityLevel.CRITICAL,
                details=f"Error reading coverage: {str(e)}",
                suggestions=["Fix coverage report generation"]
            )

class CodeComplexityGate(QualityGate):
    """Code complexity analysis gate"""

    def __init__(self, threshold: float = 10.0):
        super().__init__("Code Complexity", threshold)

    def check(self, project_root: Path) -> QualityMetric:
        """Check cyclomatic complexity using radon"""
        try:
            # Install radon if not present
            subprocess.run(["pip", "install", "radon"], capture_output=True)

            result = subprocess.run([
                "radon", "cc", str(project_root / "app"),
                "--json", "--average"
            ], capture_output=True, text=True)

            if result.returncode != 0:
                raise Exception(f"Radon execution failed: {result.stderr}")

            data = json.loads(result.stdout)

            # Calculate average complexity
            total_complexity = 0
            total_functions = 0
            high_complexity_files = []

            for file_path, metrics in data.items():
                if isinstance(metrics, list):
                    for metric in metrics:
                        if isinstance(metric, dict) and 'complexity' in metric:
                            complexity = metric['complexity']
                            total_complexity += complexity
                            total_functions += 1

                            if complexity > self.threshold:
                                high_complexity_files.append({
                                    'file': file_path,
                                    'function': metric.get('name', 'unknown'),
                                    'complexity': complexity
                                })

            avg_complexity = total_complexity / max(total_functions, 1)

            # Invert for quality level (lower complexity = better)
            adjusted_value = max(0, 20 - avg_complexity)
            level = self._determine_level(adjusted_value, 20 - self.threshold)

            suggestions = []
            if high_complexity_files:
                suggestions = [
                    "Refactor functions with high cyclomatic complexity",
                    "Break down large functions into smaller ones",
                    "Consider extracting complex logic into separate classes"
                ]
                suggestions.extend([
                    f"High complexity: {f['file']}:{f['function']} ({f['complexity']})"
                    for f in high_complexity_files[:3]
                ])

            return QualityMetric(
                name=self.name,
                value=avg_complexity,
                threshold=self.threshold,
                level=level,
                details=f"Average complexity: {avg_complexity:.1f}, High complexity files: {len(high_complexity_files)}",
                suggestions=suggestions
            )

        except Exception as e:
            return QualityMetric(
                name=self.name,
                value=0.0,
                threshold=self.threshold,
                level=QualityLevel.CRITICAL,
                details=f"Complexity analysis failed: {str(e)}",
                suggestions=["Install radon: pip install radon"]
            )

class CodeStyleGate(QualityGate):
    """Code style and formatting gate"""

    def __init__(self, threshold: float = 95.0):
        super().__init__("Code Style", threshold)

    def check(self, project_root: Path) -> QualityMetric:
        """Check code style using flake8 and black"""
        try:
            # Install tools if not present
            subprocess.run(["pip", "install", "flake8", "black", "isort"], capture_output=True)

            # Run flake8
            flake8_result = subprocess.run([
                "flake8", str(project_root / "app"),
                "--count", "--statistics", "--format=json"
            ], capture_output=True, text=True)

            # Count total lines of code
            total_lines = 0
            for py_file in (project_root / "app").rglob("*.py"):
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        total_lines += sum(1 for line in f if line.strip())
                except:
                    pass

            # Count violations
            violations = len(flake8_result.stdout.strip().split('\n')) if flake8_result.stdout.strip() else 0

            # Calculate style score (percentage of clean lines)
            style_score = max(0, 100 - (violations * 100 / max(total_lines, 1)))

            level = self._determine_level(style_score, self.threshold)

            # Check if black would make changes
            black_result = subprocess.run([
                "black", "--check", "--diff", str(project_root / "app")
            ], capture_output=True, text=True)

            black_issues = bool(black_result.returncode != 0)

            # Check import sorting
            isort_result = subprocess.run([
                "isort", "--check-only", "--diff", str(project_root / "app")
            ], capture_output=True, text=True)

            isort_issues = bool(isort_result.returncode != 0)

            suggestions = []
            if violations > 0:
                suggestions.append(f"Fix {violations} flake8 violations")
            if black_issues:
                suggestions.append("Run 'black app/' to format code")
            if isort_issues:
                suggestions.append("Run 'isort app/' to sort imports")

            details = f"Style score: {style_score:.1f}%, Violations: {violations}"
            if black_issues or isort_issues:
                details += ", Formatting issues detected"

            return QualityMetric(
                name=self.name,
                value=style_score,
                threshold=self.threshold,
                level=level,
                details=details,
                suggestions=suggestions
            )

        except Exception as e:
            return QualityMetric(
                name=self.name,
                value=0.0,
                threshold=self.threshold,
                level=QualityLevel.CRITICAL,
                details=f"Style check failed: {str(e)}",
                suggestions=["Install style tools: pip install flake8 black isort"]
            )

class TestQualityGate(QualityGate):
    """Test suite quality and effectiveness gate"""

    def __init__(self, threshold: float = 90.0):
        super().__init__("Test Quality", threshold)

    def check(self, project_root: Path) -> QualityMetric:
        """Analyze test suite quality"""
        try:
            # Run tests and collect metrics
            test_result = subprocess.run([
                "python", "-m", "pytest", "-v", "--tb=short",
                "--junitxml=test_results.xml"
            ], capture_output=True, text=True, cwd=project_root)

            # Parse test results
            junit_file = project_root / "test_results.xml"
            if not junit_file.exists():
                raise Exception("Test results XML not found")

            tree = ET.parse(junit_file)
            root = tree.getroot()

            total_tests = int(root.attrib.get('tests', 0))
            failures = int(root.attrib.get('failures', 0))
            errors = int(root.attrib.get('errors', 0))
            skipped = int(root.attrib.get('skipped', 0))

            passed_tests = total_tests - failures - errors - skipped
            test_success_rate = (passed_tests / max(total_tests, 1)) * 100

            # Calculate test comprehensiveness
            test_files = list((project_root / "tests").rglob("test_*.py"))
            source_files = list((project_root / "app").rglob("*.py"))

            test_to_source_ratio = len(test_files) / max(len(source_files), 1)

            # Combined quality score
            quality_score = (test_success_rate * 0.7) + (min(test_to_source_ratio * 100, 50) * 0.3)

            level = self._determine_level(quality_score, self.threshold)

            suggestions = []
            if failures > 0:
                suggestions.append(f"Fix {failures} failing tests")
            if errors > 0:
                suggestions.append(f"Resolve {errors} test errors")
            if test_to_source_ratio < 0.3:
                suggestions.append("Add more test files to improve coverage")
            if skipped > total_tests * 0.1:
                suggestions.append("Review and fix skipped tests")

            return QualityMetric(
                name=self.name,
                value=quality_score,
                threshold=self.threshold,
                level=level,
                details=f"Tests: {total_tests}, Passed: {passed_tests}, Failed: {failures}, Errors: {errors}",
                suggestions=suggestions
            )

        except Exception as e:
            return QualityMetric(
                name=self.name,
                value=0.0,
                threshold=self.threshold,
                level=QualityLevel.CRITICAL,
                details=f"Test analysis failed: {str(e)}",
                suggestions=["Ensure pytest is installed and tests can run"]
            )

class DocumentationGate(QualityGate):
    """Documentation completeness and quality gate"""

    def __init__(self, threshold: float = 75.0):
        super().__init__("Documentation", threshold)

    def check(self, project_root: Path) -> QualityMetric:
        """Check documentation coverage and quality"""
        try:
            # Count docstrings in Python files
            total_functions = 0
            documented_functions = 0
            total_classes = 0
            documented_classes = 0

            for py_file in (project_root / "app").rglob("*.py"):
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Simple regex-based analysis
                    import re

                    # Count functions
                    functions = re.findall(r'^def\s+\w+', content, re.MULTILINE)
                    total_functions += len(functions)

                    # Count documented functions (function followed by docstring)
                    documented_funcs = re.findall(r'def\s+\w+.*?:\s*"""', content, re.DOTALL)
                    documented_functions += len(documented_funcs)

                    # Count classes
                    classes = re.findall(r'^class\s+\w+', content, re.MULTILINE)
                    total_classes += len(classes)

                    # Count documented classes
                    documented_cls = re.findall(r'class\s+\w+.*?:\s*"""', content, re.DOTALL)
                    documented_classes += len(documented_cls)

                except:
                    continue

            # Calculate documentation coverage
            total_items = total_functions + total_classes
            documented_items = documented_functions + documented_classes
            doc_coverage = (documented_items / max(total_items, 1)) * 100

            # Check for README and other docs
            readme_exists = any([
                (project_root / "README.md").exists(),
                (project_root / "README.rst").exists(),
                (project_root / "README.txt").exists()
            ])

            api_docs_exist = (project_root / "docs").exists()

            # Adjust score based on documentation infrastructure
            adjusted_score = doc_coverage
            if readme_exists:
                adjusted_score += 5
            if api_docs_exist:
                adjusted_score += 10

            level = self._determine_level(adjusted_score, self.threshold)

            suggestions = []
            if doc_coverage < self.threshold:
                suggestions.append("Add docstrings to functions and classes")
                suggestions.append(f"Document {total_items - documented_items} undocumented items")
            if not readme_exists:
                suggestions.append("Create a README.md file")
            if not api_docs_exist:
                suggestions.append("Consider adding API documentation")

            return QualityMetric(
                name=self.name,
                value=adjusted_score,
                threshold=self.threshold,
                level=level,
                details=f"Docstring coverage: {doc_coverage:.1f}%, Functions: {documented_functions}/{total_functions}, Classes: {documented_classes}/{total_classes}",
                suggestions=suggestions
            )

        except Exception as e:
            return QualityMetric(
                name=self.name,
                value=0.0,
                threshold=self.threshold,
                level=QualityLevel.CRITICAL,
                details=f"Documentation analysis failed: {str(e)}",
                suggestions=["Fix documentation analysis setup"]
            )

class QualityGateRunner:
    """Quality gate execution and reporting"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.gates = [
            CodeCoverageGate(threshold=85.0),
            CodeComplexityGate(threshold=10.0),
            CodeStyleGate(threshold=95.0),
            TestQualityGate(threshold=90.0),
            DocumentationGate(threshold=75.0)
        ]

    def run_all_gates(self) -> QualityReport:
        """Execute all quality gates and generate report"""
        start_time = time.time()
        metrics = []
        passed_gates = []
        failed_gates = []

        for gate in self.gates:
            try:
                metric = gate.check(self.project_root)
                metrics.append(metric)

                if metric.level in [QualityLevel.EXCELLENT, QualityLevel.GOOD, QualityLevel.ACCEPTABLE]:
                    passed_gates.append(gate.name)
                else:
                    failed_gates.append(gate.name)

            except Exception as e:
                # Create error metric
                error_metric = QualityMetric(
                    name=gate.name,
                    value=0.0,
                    threshold=gate.threshold,
                    level=QualityLevel.CRITICAL,
                    details=f"Gate execution failed: {str(e)}",
                    suggestions=[f"Fix {gate.name} gate execution"]
                )
                metrics.append(error_metric)
                failed_gates.append(gate.name)

        # Calculate overall score
        total_weight = sum(gate.weight for gate in self.gates)
        weighted_score = 0

        for metric, gate in zip(metrics, self.gates):
            if metric.level == QualityLevel.EXCELLENT:
                score = 100
            elif metric.level == QualityLevel.GOOD:
                score = 85
            elif metric.level == QualityLevel.ACCEPTABLE:
                score = 75
            elif metric.level == QualityLevel.NEEDS_IMPROVEMENT:
                score = 60
            else:
                score = 0

            weighted_score += score * gate.weight

        overall_score = weighted_score / total_weight

        # Determine overall level
        if overall_score >= 90:
            overall_level = QualityLevel.EXCELLENT
        elif overall_score >= 80:
            overall_level = QualityLevel.GOOD
        elif overall_score >= 70:
            overall_level = QualityLevel.ACCEPTABLE
        elif overall_score >= 50:
            overall_level = QualityLevel.NEEDS_IMPROVEMENT
        else:
            overall_level = QualityLevel.CRITICAL

        execution_time = time.time() - start_time

        return QualityReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            overall_score=overall_score,
            overall_level=overall_level,
            metrics=metrics,
            passed_gates=passed_gates,
            failed_gates=failed_gates,
            execution_time=execution_time
        )

    def generate_report_json(self, report: QualityReport, output_path: Path):
        """Generate JSON report"""
        report_dict = asdict(report)

        with open(output_path, 'w') as f:
            json.dump(report_dict, f, indent=2, default=str)

    def generate_report_html(self, report: QualityReport, output_path: Path):
        """Generate HTML report"""
        html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Quality Report - Fingerprint Time Logger</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .header { background: #f5f5f5; padding: 20px; border-radius: 5px; }
        .metric { margin: 20px 0; padding: 15px; border-left: 4px solid #ccc; }
        .excellent { border-color: #28a745; background: #d4edda; }
        .good { border-color: #17a2b8; background: #d1ecf1; }
        .acceptable { border-color: #ffc107; background: #fff3cd; }
        .needs_improvement { border-color: #fd7e14; background: #fdebd7; }
        .critical { border-color: #dc3545; background: #f8d7da; }
        .suggestions { margin-top: 10px; }
        .suggestion { color: #666; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Quality Report</h1>
        <p><strong>Generated:</strong> {timestamp}</p>
        <p><strong>Overall Score:</strong> {overall_score:.1f}/100</p>
        <p><strong>Overall Level:</strong> {overall_level}</p>
        <p><strong>Execution Time:</strong> {execution_time:.2f}s</p>
    </div>

    <h2>Quality Gates</h2>
    {metrics_html}

    <h2>Summary</h2>
    <p><strong>Passed Gates:</strong> {passed_count}/{total_gates}</p>
    <p><strong>Failed Gates:</strong> {failed_count}/{total_gates}</p>
</body>
</html>
        """

        metrics_html = ""
        for metric in report.metrics:
            level_class = metric.level.value

            suggestions_html = ""
            if metric.suggestions:
                suggestions_html = "<div class='suggestions'>"
                for suggestion in metric.suggestions:
                    suggestions_html += f"<div class='suggestion'>• {suggestion}</div>"
                suggestions_html += "</div>"

            metrics_html += f"""
            <div class="metric {level_class}">
                <h3>{metric.name}</h3>
                <p><strong>Score:</strong> {metric.value:.1f} (Threshold: {metric.threshold})</p>
                <p><strong>Level:</strong> {metric.level.value.replace('_', ' ').title()}</p>
                <p><strong>Details:</strong> {metric.details}</p>
                {suggestions_html}
            </div>
            """

        html_content = html_template.format(
            timestamp=report.timestamp,
            overall_score=report.overall_score,
            overall_level=report.overall_level.value.replace('_', ' ').title(),
            execution_time=report.execution_time,
            metrics_html=metrics_html,
            passed_count=len(report.passed_gates),
            failed_count=len(report.failed_gates),
            total_gates=len(report.metrics)
        )

        with open(output_path, 'w') as f:
            f.write(html_content)

def main():
    """Run quality gates"""
    project_root = Path.cwd()
    runner = QualityGateRunner(project_root)

    print("🔍 Running Quality Gates...")
    report = runner.run_all_gates()

    # Generate reports
    reports_dir = project_root / "quality_reports"
    reports_dir.mkdir(exist_ok=True)

    json_path = reports_dir / f"quality_report_{int(time.time())}.json"
    html_path = reports_dir / f"quality_report_{int(time.time())}.html"

    runner.generate_report_json(report, json_path)
    runner.generate_report_html(report, html_path)

    print(f"\n📊 Quality Report Generated")
    print(f"Overall Score: {report.overall_score:.1f}/100")
    print(f"Overall Level: {report.overall_level.value.replace('_', ' ').title()}")
    print(f"Passed Gates: {len(report.passed_gates)}/{len(report.metrics)}")
    print(f"Reports: {json_path}, {html_path}")

    # Exit with appropriate code
    if report.overall_level in [QualityLevel.CRITICAL, QualityLevel.NEEDS_IMPROVEMENT]:
        exit(1)
    else:
        exit(0)

if __name__ == "__main__":
    main()