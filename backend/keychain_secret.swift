// CleanHouse Keychain adapter. Upsert values enter only through stdin and the
// upsert response never emits them. Read values travel only over a caller-owned
// anonymous file descriptor and are never placed in argv, environment, standard
// output/error, logs, or files.
import Foundation
import Security

func finish(_ payload: [String: Any], code: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: payload)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(code)
}

guard
    let request = try? JSONSerialization.jsonObject(
        with: FileHandle.standardInput.readDataToEndOfFile()
    ) as? [String: Any],
    let operation = request["operation"] as? String,
    let service = request["service"] as? String, !service.isEmpty,
    let account = request["account"] as? String, !account.isEmpty
else {
    finish(["ok": false, "status": Int(errSecParam)], code: 1)
}

let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: service,
    kSecAttrAccount as String: account,
]

if operation == "read" {
    guard let responseFdString = request["responseFd"] as? String,
          let responseFd = Int32(responseFdString), responseFd >= 3 else {
        finish(["ok": false, "status": Int(errSecParam)], code: 1)
    }
    var readQuery = query
    readQuery[kSecReturnData as String] = true
    readQuery[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(readQuery as CFDictionary, &result)
    guard status == errSecSuccess, let data = result as? Data,
          let value = String(data: data, encoding: .utf8) else {
        finish(["ok": false, "status": Int(status)], code: 1)
    }
    FileHandle(fileDescriptor: responseFd, closeOnDealloc: false).write(Data(value.utf8))
    finish(["ok": true])
}

guard operation == "upsert", let value = request["value"] as? String, !value.isEmpty else {
    finish(["ok": false, "status": Int(errSecParam)], code: 1)
}
let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8)]
let existing = SecItemCopyMatching(query as CFDictionary, nil)
let status: OSStatus
if existing == errSecSuccess {
    status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
} else if existing == errSecItemNotFound {
    var insertion = query
    insertion[kSecValueData as String] = Data(value.utf8)
    status = SecItemAdd(insertion as CFDictionary, nil)
} else {
    status = existing
}
guard status == errSecSuccess else {
    finish(["ok": false, "status": Int(status)], code: 1)
}

finish(["ok": true])
