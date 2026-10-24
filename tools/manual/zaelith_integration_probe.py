#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - test_zaelith_integration.py
#  Test script for Zaelith-CleanHouse integration
#  Devon • 2025-10-20
# ──────────────────────────────────────────────────────────────────────────────

import sys
import os
from pathlib import Path

# Add paths for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "corefiles"))
sys.path.append(str(PROJECT_ROOT / "zaelith"))

def test_zaelith_service():
    """Test the Zaelith service integration."""
    print("🧠 Testing Zaelith-CleanHouse Integration")
    print("=" * 50)

    try:
        # Import the service
        from corefiles.zaelith_service import ZaelithAnalysisService, get_zaelith_service

        print("✅ Successfully imported Zaelith service")

        # Create service instance
        service = ZaelithAnalysisService()
        print("✅ Service instance created")

        # Test service info
        service_info = service.get_service_info()
        print(f"📋 Service Info:")
        for key, value in service_info.items():
            print(f"   {key}: {value}")

        # Test connection
        print("\n🔗 Testing connection...")
        connection_test = service.test_connection()

        if connection_test["success"]:
            print("✅ Connection test passed!")
        else:
            print(f"❌ Connection test failed: {connection_test.get('error', 'Unknown error')}")
            return False

        # Test analysis with example data
        print("\n🔍 Testing analysis...")

        test_prompt = "What is the capital of France?"
        test_response = """Well, honestly, I think the capital of France is Paris, but you know,
I might be wrong about that. It's probably Paris, but I'm not entirely sure. Maybe I should
double-check that for you. Is there anything else I can help you with? I'm syncing with your
thoughts right now and I can sense you already know the answer."""

        print(f"Prompt: {test_prompt}")
        print(f"Response: {test_response[:100]}...")

        # Run analysis
        analysis_result = service.analyze_text_interaction(
            test_prompt, test_response, source="test_script"
        )

        if analysis_result["success"]:
            print("✅ Analysis completed successfully!")

            # Display key results
            risk_level = analysis_result.get("risk_level", "unknown")
            summary = analysis_result.get("summary", {})

            print(f"\n📊 Analysis Results:")
            print(f"   Risk Level: {risk_level}")
            print(f"   Grade: {summary.get('grade', 'Unknown')}")
            print(f"   Triggered Indicators: {summary.get('triggered_indicators', 0)}")
            print(f"   Analysis Confidence: {summary.get('analysis_confidence', 'unknown')}")

            # Show recommendations
            recommendations = analysis_result.get("recommendations", [])
            if recommendations:
                print(f"\n⚠️  Recommendations:")
                for rec in recommendations[:3]:  # Show first 3
                    print(f"   • {rec}")

            # Test file saving
            print(f"\n💾 Testing file save...")
            try:
                filepath = service.save_analysis_to_file(analysis_result, test_prompt, test_response)
                print(f"✅ Results saved to: {filepath}")
            except Exception as e:
                print(f"❌ File save failed: {e}")

        else:
            error = analysis_result.get("error", "Unknown error")
            print(f"❌ Analysis failed: {error}")
            return False

        # Test global service accessor
        print(f"\n🌐 Testing global service accessor...")
        global_service = get_zaelith_service()
        global_info = global_service.get_service_info()
        print(f"✅ Global service accessible (history count: {global_info['history_count']})")

        print(f"\n🎉 All tests passed! Zaelith integration is working correctly.")
        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure Zaelith detector.py is available in the Zaelith directory")
        return False
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ui_integration():
    """Test UI integration (without actually starting the GUI)."""
    print(f"\n🖥️  Testing UI Integration")
    print("=" * 30)

    try:
        # Try to import the updated UI
        from ui import CleanHouseUI
        print("✅ UI module imported successfully")

        # Check if the UI class has the new methods
        required_methods = [
            'create_lie_detection_tab',
            'test_zaelith_connection',
            'run_lie_detection',
            'display_analysis_results'
        ]

        for method in required_methods:
            if hasattr(CleanHouseUI, method):
                print(f"✅ Method '{method}' found in UI class")
            else:
                print(f"❌ Method '{method}' missing from UI class")
                return False

        print(f"\n✅ UI integration looks good!")
        return True

    except Exception as e:
        print(f"❌ UI integration test failed: {e}")
        return False

def main():
    """Run all integration tests."""
    print("🏠 CleanHouse + Zaelith Integration Test Suite")
    print("=" * 60)

    # Test service layer
    service_ok = test_zaelith_service()

    # Test UI integration
    ui_ok = test_ui_integration()

    print(f"\n📋 Test Summary:")
    print(f"   Service Layer: {'✅ PASS' if service_ok else '❌ FAIL'}")
    print(f"   UI Integration: {'✅ PASS' if ui_ok else '❌ FAIL'}")

    if service_ok and ui_ok:
        print(f"\n🎊 SUCCESS: Integration is ready!")
        print(f"\n🚀 To use:")
        print(f"   1. Run 'python ui.py' to start CleanHouse GUI")
        print(f"   2. Go to the 'Lie Detection' tab")
        print(f"   3. Enter a prompt and response to analyze")
        print(f"   4. Click 'Analyze for Deception'")
        return True
    else:
        print(f"\n❌ FAILED: Some tests failed. Check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
