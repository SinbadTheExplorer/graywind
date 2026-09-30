// Long-lived text-to-speech helper: keeps Tom loaded so a scaffold costs ~0.1s
// instead of the ~1.2s startup `say` pays on every call (measured 2026-09-30).
//
// Built on demand by avatar/voice_client.py into ~/.mavis/bin/. Protocol, one
// JSON object per line:
//   out: {"ready": true, "voice": "<id>"}            (once, after a prewarm)
//   in:  {"id": 1, "text": "...", "path": "/abs/out.wav"}
//   out: {"id": 1, "ok": true, "seconds": 0.12, "audio_seconds": 5.3}
// Output matches `say --data-format=LEF32@22050`: WAV, float32 LE, mono, 22050Hz.
// First drafted by the `delegate` model; its voice check, file close, resampler
// and error reporting were fixed in review.
import AppKit
import AVFoundation

setvbuf(stdout, nil, _IOLBF, 0)

let sampleRate = 22050.0

func emit(_ obj: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: obj),
       let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

struct Failure: Error { let message: String }

// Exactly this voice or nothing: a silent fallback to the system voice would
// change his character after voice conversion without anyone noticing.
let voiceID = CommandLine.arguments.dropFirst().first ?? "com.apple.voice.enhanced.en-US.Tom"
let voiceName = NSSpeechSynthesizer.VoiceName(rawValue: voiceID)
guard NSSpeechSynthesizer.availableVoices.contains(voiceName),
      let synth = NSSpeechSynthesizer(voice: voiceName) else {
    emit(["ready": false, "error": "voice not installed: \(voiceID)"])
    exit(1)
}

func speak(_ text: String, to url: URL, timeout: TimeInterval = 30) throws {
    guard synth.startSpeaking(text, to: url) else { throw Failure(message: "startSpeaking refused") }
    let deadline = Date().addingTimeInterval(timeout)
    while synth.isSpeaking && Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.005))
    }
    if synth.isSpeaking {
        synth.stopSpeaking()
        throw Failure(message: "synthesis timeout")
    }
}

func resampled(_ buffer: AVAudioPCMBuffer, to format: AVAudioFormat) throws -> AVAudioPCMBuffer {
    guard let converter = AVAudioConverter(from: buffer.format, to: format),
          let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(
              Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate + 1)) else {
        throw Failure(message: "no converter")
    }
    var fed = false
    var error: NSError?
    converter.convert(to: out, error: &error) { _, status in
        if fed { status.pointee = .endOfStream; return nil }
        fed = true
        status.pointee = .haveData
        return buffer
    }
    if let error { throw error }
    return out
}

// Returns the frame count. The output file is closed when this returns, so
// the reply below never points at a half-written wav.
func aiffToWav(_ aiff: URL, _ wav: URL) throws -> AVAudioFrameCount {
    let input = try AVAudioFile(forReading: aiff)
    guard let buffer = AVAudioPCMBuffer(pcmFormat: input.processingFormat,
                                        frameCapacity: AVAudioFrameCount(input.length)),
          let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate,
                                     channels: 1, interleaved: false) else {
        throw Failure(message: "cannot allocate audio buffer")
    }
    try input.read(into: buffer)
    let out = buffer.format.sampleRate == sampleRate && buffer.format.channelCount == 1
        ? buffer : try resampled(buffer, to: format)
    let settings: [String: Any] = [
        AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: sampleRate,
        AVNumberOfChannelsKey: 1, AVLinearPCMBitDepthKey: 32,
        AVLinearPCMIsFloatKey: true, AVLinearPCMIsBigEndianKey: false,
    ]
    let file = try AVAudioFile(forWriting: wav, settings: settings,
                               commonFormat: .pcmFormatFloat32, interleaved: false)
    try file.write(from: out)
    return out.frameLength
}

func render(_ text: String, _ path: String) throws -> AVAudioFrameCount {
    let wav = URL(fileURLWithPath: path)
    let aiff = wav.deletingLastPathComponent()
        .appendingPathComponent(UUID().uuidString).appendingPathExtension("aiff")
    defer { try? FileManager.default.removeItem(at: aiff) }
    try speak(text, to: aiff)
    return try aiffToWav(aiff, wav)
}

// The first utterance costs ~1s (voice load); pay it before `ready`.
let warm = URL(fileURLWithPath: NSTemporaryDirectory())
    .appendingPathComponent("mavis-speaker-\(UUID().uuidString).wav")
// A warm-up that fails means every request would too: say so, and exit.
do {
    defer { try? FileManager.default.removeItem(at: warm) }
    _ = try render("Hello there.", warm.path)
} catch {
    emit(["ready": false, "error": "warm-up failed: \(error)"])
    exit(1)
}
emit(["ready": true, "voice": voiceID])

while let line = readLine() {
    guard let request = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any] else {
        emit(["id": NSNull(), "ok": false, "error": "bad request"])
        continue
    }
    let id = request["id"] ?? NSNull()
    guard let text = request["text"] as? String, let path = request["path"] as? String else {
        emit(["id": id, "ok": false, "error": "bad request: needs text and path"])
        continue
    }
    let start = Date()
    do {
        let frames = try render(text, path)
        emit(["id": id, "ok": true, "seconds": Date().timeIntervalSince(start),
              "audio_seconds": Double(frames) / sampleRate])
    } catch {
        emit(["id": id, "ok": false, "error": "\(error)"])
    }
}
