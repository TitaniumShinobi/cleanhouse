import Foundation

#if canImport(FoundationModels)
import FoundationModels
#endif

func emitJSONObject(_ object: [String: Any], exitCode: Int32 = 0) -> Never {
    let data = (try? JSONSerialization.data(withJSONObject: object, options: [])) ?? Data("{}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(exitCode)
}

func unavailable(_ reason: String, limitations: [String] = []) -> Never {
    emitJSONObject([
        "status": "unavailable",
        "provider": "apple_foundation_models",
        "reason": reason,
        "limitations": limitations,
    ])
}

func payloadText(_ payload: [String: Any]) -> String {
    guard JSONSerialization.isValidJSONObject(payload),
          let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
          let text = String(data: data, encoding: .utf8) else {
        return "{}"
    }
    return text
}

func errorSummary(_ error: Error) -> String {
    let nsError = error as NSError
    var parts = ["\(nsError.domain) code \(nsError.code): \(error.localizedDescription)"]
    let underlying = nsError.userInfo[NSUnderlyingErrorKey] as? NSError
    if let underlying {
        parts.append("\(underlying.domain) code \(underlying.code): \(underlying.localizedDescription)")
    }
    let multiple = nsError.userInfo[NSMultipleUnderlyingErrorsKey] as? [NSError] ?? []
    for item in multiple.prefix(3) {
        parts.append("\(item.domain) code \(item.code): \(item.localizedDescription)")
        let nested = item.userInfo[NSMultipleUnderlyingErrorsKey] as? [NSError] ?? []
        for nestedItem in nested.prefix(2) {
            parts.append("\(nestedItem.domain) code \(nestedItem.code): \(nestedItem.localizedDescription)")
        }
    }
    return parts.joined(separator: " | ")
}

#if canImport(FoundationModels)
@available(macOS 26.0, *)
func insightSchema() throws -> GenerationSchema {
    let stringSchema = DynamicGenerationSchema(type: String.self)
    let root = DynamicGenerationSchema(
        name: "CleanHouseInsightGuidance",
        description: "Structured read-only Insight guidance for a bounded CleanHouse EvidenceContext.",
        properties: [
            DynamicGenerationSchema.Property(
                name: "plain_language_summary",
                description: "A short explanation of what the selected CleanHouse evidence says. Do not add facts that are not in the evidence context.",
                schema: stringSchema
            ),
            DynamicGenerationSchema.Property(
                name: "why_it_matters",
                description: "Why this evidence matters operationally. Do not invent threat status, app ownership, process ownership, validation state, or destination meaning.",
                schema: stringSchema
            ),
            DynamicGenerationSchema.Property(
                name: "recommended_next_steps",
                description: "Three to five read-only next steps. Recommendations must not mutate system state.",
                schema: DynamicGenerationSchema(arrayOf: stringSchema, minimumElements: 0, maximumElements: 5)
            ),
            DynamicGenerationSchema.Property(
                name: "confidence",
                description: "Use high, medium, or low based only on the supplied evidence context.",
                schema: DynamicGenerationSchema(name: "CleanHouseInsightConfidence", anyOf: ["high", "medium", "low"])
            ),
            DynamicGenerationSchema.Property(
                name: "limitations",
                description: "Evidence limitations, including missing evidence_refs when applicable.",
                schema: DynamicGenerationSchema(arrayOf: stringSchema, minimumElements: 0, maximumElements: 8)
            ),
        ]
    )
    return try GenerationSchema(root: root, dependencies: [])
}

@available(macOS 26.0, *)
func runFoundationModels(payload: [String: Any]) async {
    let model = SystemLanguageModel.default
    switch model.availability {
    case .available:
        break
    case .unavailable(let reason):
        unavailable("Apple Foundation Models are unavailable: \(String(describing: reason)).")
    @unknown default:
        unavailable("Apple Foundation Models availability is unknown on this runtime.")
    }

    let instructions = """
    You are Insight inside CleanHouse Network's Evidence Command Center.
    Use only the bounded EvidenceContext JSON supplied by CleanHouse.
    Return structured actionable guidance only.
    Do not act as a freeform chatbot.
    Do not invent app ownership, process ownership, threat status, validation state, or destination meaning.
    Valorie owns validation language. Aurora owns report language. Zaelith remains text-in/audit-out.
    Recommended next steps must be read-only guidance and must not mutate system state.
    If evidence_refs is empty, include a clear limitation that evidence references are missing.
    If evidence_refs is not empty, do not say evidence references are missing.
    Do not describe a connection as risky, suspicious, safe, malicious, or benign unless the supplied severity, validation_state, summary, tags, or reasons explicitly say so.
    """
    let prompt = """
    EvidenceContext:
    \(payloadText(payload))
    """

    do {
        let session = LanguageModelSession(instructions: instructions)
        let response = try await session.respond(to: prompt, schema: try insightSchema())
        let data = Data(response.content.jsonString.utf8)
        let object = try JSONSerialization.jsonObject(with: data, options: []) as? [String: Any]
        emitJSONObject([
            "status": "ok",
            "provider": "apple_foundation_models",
            "insight": object ?? [:],
        ])
    } catch {
        unavailable("Apple Foundation Models request failed: \(errorSummary(error)).")
    }
}
#endif

let input = FileHandle.standardInput.readDataToEndOfFile()
guard !input.isEmpty else {
    unavailable("EvidenceContext payload is required.")
}
guard let object = try? JSONSerialization.jsonObject(with: input, options: []),
      let payload = object as? [String: Any] else {
    unavailable("EvidenceContext payload must be JSON.")
}

#if canImport(FoundationModels)
if #available(macOS 26.0, *) {
    Task {
        await runFoundationModels(payload: payload)
    }
    dispatchMain()
} else {
    unavailable("Foundation Models framework requires macOS 26 or newer.")
}
#else
unavailable("Foundation Models framework is not available to this Swift runtime.")
#endif
