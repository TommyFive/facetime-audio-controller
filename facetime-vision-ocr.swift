import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count >= 2 else { fputs("usage: ocr image\n",stderr); exit(64) }
let url=URL(fileURLWithPath:CommandLine.arguments[1])
let req=VNRecognizeTextRequest()
req.recognitionLevel = .fast
req.usesLanguageCorrection = false
req.recognitionLanguages = ["de-DE","en-US"]
try VNImageRequestHandler(url:url,options:[:]).perform([req])
for r in req.results ?? [] {
    if let text=r.topCandidates(1).first?.string {
        print(text)
    }
}
