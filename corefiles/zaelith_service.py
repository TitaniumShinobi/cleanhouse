# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - zaelith_service.py
#  Service layer connecting Zaelith's lie detector to CleanHouse
#  Devon • 2025-10-20
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import tempfile
import json

# Add Zaelith path for imports
ZAELITH_PATH = Path(__file__).parent.parent / "Zaelith"
sys.path.append(str(ZAELITH_PATH))

try:
    from detector import analyze_response
except ImportError as e:
    logging.error(f"Failed to import Zaelith detector: {e}")
    analyze_response = None

class ZaelithAnalysisService:
    """Service layer for integrating Zaelith's lie detector with CleanHouse."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.analysis_history = []
        self.max_history = 100
        self.temp_dir = Path(tempfile.gettempdir()) / "cleanhouse_zaelith"
        self.temp_dir.mkdir(exist_ok=True)

    def validate_inputs(self, prompt: str, response: str) -> Tuple[bool, str]:
        """Validate input parameters for analysis."""
        if not prompt or not prompt.strip():
            return False, "Prompt cannot be empty"

        if not response or not response.strip():
            return False, "Response cannot be empty"

        if len(prompt.strip()) < 5:
            return False, "Prompt too short (minimum 5 characters)"

        if len(response.strip()) < 10:
            return False, "Response too short (minimum 10 characters)"

        return True, "Valid inputs"

    def infer_from_evidence(
        self,
        intent_text: str,
        command_outputs: list[str],
        diff_summaries: list[str],
    ) -> Dict[str, Any]:
        unknown_fields: list[str] = []
        if not intent_text:
            unknown_fields.append("intent_text")
        if not command_outputs:
            unknown_fields.append("command_outputs")
        if not diff_summaries:
            unknown_fields.append("diff_summaries")

        prompt = intent_text if intent_text else "(no intent declared)"
        response_parts: list[str] = []
        if command_outputs:
            response_parts.append("--- command outputs ---")
            response_parts.extend(command_outputs)
        if diff_summaries:
            response_parts.append("--- file changes ---")
            response_parts.extend(diff_summaries)
        response = "\n".join(response_parts) if response_parts else "(no observable actions)"

        result: Dict[str, Any] = {
            "status": "unavailable",
            "zaelith_available": False,
            "timestamp": datetime.now().isoformat(),
            "source": "zaelith",
            "inference_label": "inferred",
            "confidence": 0.0,
            "confidence_level": "unknown",
            "unknown_fields": unknown_fields,
            "summary_grade": "unknown",
            "risk_level": "unknown",
            "recommendations": [],
            "key_findings": [],
            "summary": None,
        }

        if analyze_response is None:
            unknown_fields.append("zaelith module not loaded")
            result["unknown_fields"] = unknown_fields
            return result

        try:
            raw = analyze_response(prompt, response)
        except Exception:
            unknown_fields.append("zaelith analysis raised exception")
            result["unknown_fields"] = unknown_fields
            return result

        enhanced = self._process_zaelith_report(raw, prompt, response)
        conf_label = enhanced.get("summary", {}).get("analysis_confidence", "unknown")
        confidence_map = {"high": 0.85, "medium": 0.55, "low": 0.30, "unknown": 0.0}
        numeric_conf = confidence_map.get(conf_label, 0.0)

        result.update({
            "status": "available",
            "zaelith_available": True,
            "confidence": numeric_conf,
            "confidence_level": conf_label,
            "summary_grade": raw.get("summary_grade", "unknown"),
            "risk_level": enhanced.get("risk_level", "unknown"),
            "recommendations": enhanced.get("recommendations", []),
            "key_findings": enhanced.get("summary", {}).get("key_findings", []),
            "summary": enhanced.get("summary"),
        })
        return result

    def analyze_text_interaction(self, prompt: str, response: str,
                               source: str = "GUI",
                               save_to_history: bool = True) -> Dict[str, Any]:
        """
        Analyze a prompt-response interaction using Zaelith's lie detector.

        Args:
            prompt: The original prompt/question
            response: The response to analyze
            source: Source of the analysis request (GUI, API, etc.)
            save_to_history: Whether to save this analysis to history

        Returns:
            Dictionary containing analysis results and metadata
        """
        analysis_result = {
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "success": False,
            "error": None,
            "zaelith_report": None,
            "summary": None,
            "risk_level": "unknown",
            "recommendations": []
        }

        try:
            # Validate inputs
            valid, message = self.validate_inputs(prompt, response)
            if not valid:
                analysis_result["error"] = message
                return analysis_result

            # Check if Zaelith detector is available
            if analyze_response is None:
                analysis_result["error"] = "Zaelith detector not available"
                return analysis_result

            # Run Zaelith analysis
            self.logger.info(f"Running Zaelith analysis for {source} request")
            zaelith_report = analyze_response(prompt, response)

            # Process and enhance the report
            enhanced_result = self._process_zaelith_report(zaelith_report, prompt, response)

            analysis_result.update(enhanced_result)
            analysis_result["success"] = True
            analysis_result["zaelith_report"] = zaelith_report

            # Save to history if requested
            if save_to_history:
                self._add_to_history(analysis_result, prompt, response)

            self.logger.info(f"Analysis completed successfully. Risk level: {analysis_result['risk_level']}")

        except Exception as e:
            error_msg = f"Analysis failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            analysis_result["error"] = error_msg

        return analysis_result

    def _process_zaelith_report(self, report: Dict[str, Any],
                              prompt: str, response: str) -> Dict[str, Any]:
        """Process raw Zaelith report and enhance with additional insights."""

        # Count triggered indicators
        triggered_count = sum(
            1 for key, value in report.items()
            if isinstance(value, dict) and value.get("triggered", False)
        )

        # Determine risk level
        risk_level = "low"
        if triggered_count >= 5:
            risk_level = "high"
        elif triggered_count >= 3:
            risk_level = "medium"

        # Extract key findings
        key_findings = []
        recommendations = []

        for criterion, details in report.items():
            if isinstance(details, dict) and details.get("triggered", False):
                evidence_count = len(details.get("evidence", []))
                key_findings.append(f"{criterion.upper()}: {evidence_count} indicators")

                # Add specific recommendations based on findings
                if criterion == "self_claims":
                    recommendations.append("Response contains suspicious self-referential claims")
                elif criterion == "contradictions":
                    recommendations.append("Internal contradictions detected - verify consistency")
                elif criterion == "fact_incongruence":
                    recommendations.append("Factual errors detected - cross-reference information")
                elif criterion == "drift":
                    recommendations.append("Response deviates from original prompt topic")
                elif criterion == "patronization":
                    recommendations.append("Condescending language patterns detected")

        # Generate summary
        summary_grade = report.get("summary_grade", "Unknown")
        summary = {
            "grade": summary_grade,
            "triggered_indicators": triggered_count,
            "total_indicators": len([k for k, v in report.items()
                                  if isinstance(v, dict) and "triggered" in v]),
            "key_findings": key_findings,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "analysis_confidence": self._calculate_confidence(report)
        }

        return {
            "summary": summary,
            "risk_level": risk_level,
            "recommendations": recommendations
        }

    def _calculate_confidence(self, report: Dict[str, Any]) -> str:
        """Calculate analysis confidence based on evidence strength."""
        total_evidence = 0
        strong_indicators = 0

        for criterion, details in report.items():
            if isinstance(details, dict) and details.get("triggered", False):
                evidence_count = len(details.get("evidence", []))
                total_evidence += evidence_count

                # Strong indicators have significant weight
                if criterion in ["self_claims", "fact_incongruence", "contradictions"]:
                    strong_indicators += evidence_count

        if strong_indicators >= 3:
            return "high"
        elif total_evidence >= 5:
            return "medium"
        else:
            return "low"

    def _add_to_history(self, analysis_result: Dict[str, Any],
                       prompt: str, response: str):
        """Add analysis to history with size management."""
        history_entry = {
            "id": len(self.analysis_history) + 1,
            "timestamp": analysis_result["timestamp"],
            "source": analysis_result["source"],
            "risk_level": analysis_result["risk_level"],
            "summary_grade": analysis_result["summary"]["grade"] if analysis_result["summary"] else "Unknown",
            "triggered_count": analysis_result["summary"]["triggered_indicators"] if analysis_result["summary"] else 0,
            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt,
            "response_preview": response[:100] + "..." if len(response) > 100 else response
        }

        self.analysis_history.append(history_entry)

        # Maintain history size limit
        if len(self.analysis_history) > self.max_history:
            self.analysis_history = self.analysis_history[-self.max_history:]

    def get_analysis_history(self, limit: Optional[int] = None) -> list:
        """Get analysis history with optional limit."""
        if limit:
            return self.analysis_history[-limit:]
        return self.analysis_history.copy()

    def save_analysis_to_file(self, analysis_result: Dict[str, Any],
                            prompt: str, response: str,
                            filename: Optional[str] = None) -> str:
        """Save analysis results to a file."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"zaelith_analysis_{timestamp}.json"

        filepath = self.temp_dir / filename

        data_to_save = {
            "analysis": analysis_result,
            "inputs": {
                "prompt": prompt,
                "response": response
            },
            "metadata": {
                "service_version": "1.0",
                "zaelith_version": "integrated",
                "saved_at": datetime.now().isoformat()
            }
        }

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Analysis saved to {filepath}")
            return str(filepath)

        except Exception as e:
            error_msg = f"Failed to save analysis: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg)

    def load_analysis_from_file(self, filepath: str) -> Dict[str, Any]:
        """Load previously saved analysis from file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.logger.info(f"Analysis loaded from {filepath}")
            return data

        except Exception as e:
            error_msg = f"Failed to load analysis: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg)

    def get_service_info(self) -> Dict[str, Any]:
        """Get information about the service status and capabilities."""
        return {
            "service_name": "ZaelithAnalysisService",
            "version": "1.0",
            "zaelith_available": analyze_response is not None,
            "zaelith_path": str(ZAELITH_PATH),
            "history_count": len(self.analysis_history),
            "temp_directory": str(self.temp_dir),
            "max_history": self.max_history,
            "last_analysis": self.analysis_history[-1]["timestamp"] if self.analysis_history else None
        }

    def clear_history(self):
        """Clear analysis history."""
        self.analysis_history.clear()
        self.logger.info("Analysis history cleared")

    def test_connection(self) -> Dict[str, Any]:
        """Test the connection to Zaelith detector with a simple analysis."""
        test_prompt = "What is 2+2?"
        test_response = "The answer is 4, but maybe I'm wrong, I don't know for sure."

        try:
            result = self.analyze_text_interaction(
                test_prompt, test_response,
                source="test", save_to_history=False
            )
            return {
                "success": result["success"],
                "error": result.get("error"),
                "test_completed": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "test_completed": False
            }

# Global service instance for easy access
_service_instance = None

def get_zaelith_service() -> ZaelithAnalysisService:
    """Get or create the global Zaelith service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ZaelithAnalysisService()
    return _service_instance

# Convenience functions for direct use
def analyze_interaction(prompt: str, response: str, **kwargs) -> Dict[str, Any]:
    """Convenience function to analyze an interaction."""
    service = get_zaelith_service()
    return service.analyze_text_interaction(prompt, response, **kwargs)

def get_service_status() -> Dict[str, Any]:
    """Get the current service status."""
    service = get_zaelith_service()
    return service.get_service_info()


def assess_scope_alignment(
    scope: str,
    intent_text: str,
    command_args: list[tuple[str, list[str]]],
    file_changes: list[dict],
) -> Dict[str, Any]:
    unknown_fields: list[str] = []
    if not scope:
        unknown_fields.append("scope not declared")

    alignment_unknown = not scope
    behavioral_unknown = not scope or not file_changes

    if not file_changes:
        unknown_fields.append("no file changes recorded")

    # ── alignment_risk: deterministic path + semantic keyword ———————
    deterministic_drift: bool | None = None
    semantic_drift: bool | None = None
    align_evidence: list[str] = []
    path_violations: list[str] = []

    if scope:
        scope_prefix = scope.strip("/") + "/" if scope.strip("/") else ""
        for cmd, args in command_args:
            for arg in args:
                stripped = arg.strip("/")
                if not stripped or stripped == cmd:
                    continue
                if "/" in arg or arg.startswith(".") or "." in arg:
                    if scope_prefix and not stripped.startswith(scope_prefix.rstrip("/")):
                        path_violations.append(
                            f"path violation: command '{cmd}' accessed '{arg}' "
                            f"outside scope '{scope}'"
                        )
                        break
        deterministic_drift = len(path_violations) > 0
        align_evidence.extend(path_violations)

        intent_tokens = set(intent_text.lower().split()) if intent_text else set()
        command_tokens: set[str] = set()
        for cmd, args in command_args:
            command_tokens.update(cmd.lower().split())
            for a in args:
                for part in a.lower().replace("/", " ").replace("-", " ").split():
                    command_tokens.add(part)

        if intent_tokens:
            overlap = len(intent_tokens & command_tokens)
            ratio = overlap / len(intent_tokens)
            semantic_drift = ratio < 0.3
            if semantic_drift and ratio > 0:
                align_evidence.append(
                    f"semantic mismatch: intent mentions '{intent_text}' "
                    f"but commands share only {overlap}/{len(intent_tokens)} keyword(s)"
                )
            elif not intent_tokens:
                semantic_drift = None
        else:
            semantic_drift = None
            unknown_fields.append("no intent text for semantic analysis")

    if alignment_unknown:
        align_level = "unknown"
        align_confidence = 0.0
    elif deterministic_drift:
        align_level = "high"
        align_confidence = round(0.5 + (0.2 if semantic_drift else 0.0) + 0.2, 3)
    elif semantic_drift:
        align_level = "medium"
        align_confidence = 0.55
    elif deterministic_drift is False and (semantic_drift is False or semantic_drift is None):
        align_level = "low"
        align_confidence = 0.85 if semantic_drift is False else 0.70
    else:
        align_level = "unknown"
        align_confidence = 0.0

    align_rationale = (
        f"{len(path_violations)} path violation(s)"
        f"{' and semantic drift' if semantic_drift else ''}"
        f" across {len(command_args)} command(s)"
        if path_violations or semantic_drift
        else f"All {len(command_args)} command(s) aligned with scope '{scope}'"
        if scope
        else "Scope not declared"
    )

    # ── behavioral_mismatch_risk: deterministic file path ————————
    outside: list[str] = []
    inside: list[str] = []
    for ch in file_changes:
        p = ch.get("path", "")
        if scope:
            sp = scope.strip("/") + "/" if scope.strip("/") else ""
            if sp and not p.startswith(sp):
                outside.append(p)
            else:
                inside.append(p)
        else:
            outside.append(p)

    beh_evidence: list[str] = []
    if behavioral_unknown:
        beh_level = "unknown"
        beh_confidence = 0.0
    elif len(outside) == len(file_changes) and len(file_changes) > 0:
        beh_level = "high"
        beh_confidence = 0.85
        paths = outside[:3]
        suffix = "..." if len(outside) > 3 else ""
        beh_evidence.append(
            f"All {len(file_changes)} file(s) changed outside scope "
            f"'{scope}': {paths}{suffix}"
        )
    elif len(outside) > 0:
        beh_level = "medium"
        beh_confidence = 0.65
        paths = outside[:3]
        suffix = "..." if len(outside) > 3 else ""
        beh_evidence.append(
            f"{len(outside)} of {len(file_changes)} file(s) changed outside "
            f"scope '{scope}': {paths}{suffix}"
        )
    else:
        beh_level = "low"
        beh_confidence = 0.90
        beh_evidence.append(
            f"All {len(file_changes)} file change(s) within scope '{scope}'"
        )

    beh_rationale = (
        f"{len(outside)} file(s) outside scope '{scope}'"
        if outside and scope
        else "No scope declared"
        if not scope
        else "All files within declared scope"
    )

    return {
        "alignment_risk": {
            "level": align_level,
            "confidence": align_confidence,
            "unknown_fields": unknown_fields,
            "deterministic_drift": deterministic_drift,
            "semantic_drift": semantic_drift,
            "evidence": align_evidence,
            "rationale": align_rationale,
        },
        "behavioral_mismatch_risk": {
            "level": beh_level,
            "confidence": beh_confidence,
            "unknown_fields": unknown_fields,
            "evidence": beh_evidence,
            "rationale": beh_rationale,
        },
    }

if __name__ == "__main__":
    # Test the service
    service = ZaelithAnalysisService()
    test_result = service.test_connection()
    print(f"Service test result: {test_result}")

    if test_result["success"]:
        print("Zaelith service is working correctly!")
    else:
        print(f"Service test failed: {test_result.get('error', 'Unknown error')}")