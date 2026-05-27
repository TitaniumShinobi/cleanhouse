# Zaelith-CleanHouse Integration

This integration connects Zaelith's lie detection capabilities with CleanHouse's security monitoring interface, providing a unified GUI for analyzing potentially deceptive text responses.

## Architecture Overview

```
CleanHouse (ui.py)
    ↓
ZaelithAnalysisService (corefiles/zaelith_service.py)
    ↓  
Zaelith Detector (Zaelith/detector.py)
    ↓
Analysis Results → GUI Display
```

## Components

### 1. Service Layer (`corefiles/zaelith_service.py`)
- **ZaelithAnalysisService**: Main service class that interfaces with Zaelith
- **Features**:
  - Text validation and preprocessing
  - Analysis result processing and enhancement
  - History management (up to 100 analyses)
  - File I/O for saving/loading analyses
  - Service health monitoring

### 2. GUI Integration (`ui.py`)
- **New "Lie Detection" tab** with:
  - Service status indicator
  - Input fields for prompt and response text
  - Real-time analysis with progress feedback
  - Multi-tabbed results display (Summary, Detailed, History)
  - Analysis history browser
  - Export functionality

### 3. Analysis Pipeline
1. **Input Validation**: Ensures minimum text lengths and proper formatting
2. **Zaelith Analysis**: Runs detector.analyze_response() with enhanced error handling
3. **Result Enhancement**: Adds risk levels, confidence scores, and recommendations
4. **Display Processing**: Formats results for GUI with color coding and structure
5. **History Storage**: Maintains session history with metadata

## Key Features

### Analysis Capabilities
- **Deception Indicators**: Detects ambiguity, contradictions, patronization, misdirection
- **Fact Checking**: Cross-references against known facts
- **Behavioral Analysis**: Identifies suspicious self-referential claims
- **Risk Assessment**: Provides low/medium/high risk categorization
- **Confidence Scoring**: Evaluates analysis reliability

### User Interface
- **Interactive Analysis**: Point-and-click lie detection from GUI
- **Real-time Results**: Immediate feedback with colored risk indicators
- **Example Loading**: Pre-loaded suspicious text for testing
- **History Management**: Browse previous analyses with timestamps
- **Export Options**: Save detailed reports to JSON files

### Integration Benefits
- **Unified Interface**: Single GUI for both security monitoring and lie detection
- **Enhanced Monitoring**: Adds text analysis to CleanHouse's file integrity monitoring
- **Session Management**: Maintains analysis history within CleanHouse sessions
- **Error Handling**: Robust error handling with user-friendly messages

## Usage Guide

### Starting the Integration
1. Ensure Zaelith detector is available in `Zaelith/detector.py`
2. Run CleanHouse: `python ui.py`
3. Navigate to the "Lie Detection" tab

### Running Analysis
1. **Test Connection**: Click "Test Connection" to verify Zaelith is working
2. **Enter Text**: 
   - Paste the original prompt in the first text box
   - Paste the response to analyze in the second text box
3. **Analyze**: Click "Analyze for Deception" 
4. **Review Results**: Check the Summary tab for key findings

### Interpreting Results

#### Risk Levels
- 🟢 **LOW**: Few or weak deception indicators
- 🟡 **MEDIUM**: Some concerning patterns detected  
- 🔴 **HIGH**: Multiple strong deception indicators

#### Key Indicators
- **Self Claims**: Suspicious self-referential statements
- **Contradictions**: Internal logical inconsistencies
- **Fact Incongruence**: Statements contradicting known facts
- **Drift**: Response diverging from original prompt
- **Patronization**: Condescending language patterns

### Advanced Features
- **History Browser**: Double-click history entries to view details
- **Export Results**: Save detailed JSON reports for external analysis
- **Service Monitoring**: Real-time status of Zaelith detector availability

## Configuration

### File Locations
```
CleanHouse/
├── ui.py                          # Main GUI with lie detection tab
├── corefiles/
│   └── zaelith_service.py        # Service layer integration
├── Zaelith/
│   ├── detector.py               # Zaelith lie detector engine
│   └── brain.py                  # Zaelith CLI interface
└── tools/manual/zaelith_integration_probe.py # Integration probe
```

### Dependencies
- **CleanHouse**: tkinter, threading, pathlib, json, logging
- **Zaelith**: re, typing (standard library)
- **Integration**: tempfile for result caching

## Error Handling

### Common Issues
1. **"Zaelith service not available"**
   - Check that `Zaelith/detector.py` exists and is readable
   - Verify the detector module imports correctly

2. **"Analysis failed"**
   - Ensure input text meets minimum length requirements (5+ chars prompt, 10+ chars response)
   - Check for special characters that might break analysis

3. **"Service Unavailable"**
   - Restart CleanHouse to reinitialize the service
   - Check log files for detailed error messages

### Debugging
- Check the CleanHouse logs in `logs/cleanhouse.log` for detailed error information
- Use the "Test Connection" button to verify Zaelith functionality
- Run `python tools/manual/zaelith_integration_probe.py` for comprehensive diagnostics

## Testing

Run the integration test suite:
```bash
cd CleanHouse
python tools/manual/zaelith_integration_probe.py
```

This will verify:
- ✅ Service layer functionality
- ✅ Zaelith detector connectivity  
- ✅ Analysis pipeline operation
- ✅ File I/O capabilities
- ✅ GUI integration points

## Future Enhancements

### Planned Features
- **Real-time Analysis**: Monitor clipboard/input streams for automatic analysis
- **Batch Processing**: Analyze multiple text files simultaneously  
- **Custom Rules**: User-configurable deception indicators
- **API Integration**: REST API for external system integration
- **Advanced Reporting**: Statistical analysis across analysis history

### Integration Opportunities
- **Email Scanning**: Integrate with email clients for phishing detection
- **Chat Monitoring**: Real-time analysis of chat messages
- **Document Analysis**: Bulk analysis of document repositories
- **Security Alerting**: Integration with CleanHouse's security notification system

## Support

For integration issues:
1. Check this README for common solutions
2. Run the test script for diagnostics  
3. Review log files for detailed error information
4. Verify all file paths and permissions are correct

The integration maintains backward compatibility with existing CleanHouse functionality while adding powerful lie detection capabilities through a clean, intuitive interface.
