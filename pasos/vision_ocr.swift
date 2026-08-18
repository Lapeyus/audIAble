// OCR de páginas escaneadas con el framework Vision de macOS.
// Uso: swift vision_ocr.swift <idiomas> <imagen> [imagen...]
// Por cada imagen imprime "###FILE:<ruta>" seguido del texto reconocido.
import Foundation
import Vision
import AppKit

let argumentos = CommandLine.arguments
guard argumentos.count >= 3 else {
    FileHandle.standardError.write("uso: swift vision_ocr.swift <es-ES,en-US> imagen...\n".data(using: .utf8)!)
    exit(1)
}
let idiomas = argumentos[1].split(separator: ",").map(String.init)

for ruta in argumentos.dropFirst(2) {
    print("###FILE:\(ruta)")
    guard let imagen = NSImage(contentsOfFile: ruta),
          let cg = imagen.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("###ERROR:no se pudo abrir la imagen")
        continue
    }
    let peticion = VNRecognizeTextRequest()
    peticion.recognitionLevel = .accurate
    peticion.recognitionLanguages = idiomas
    peticion.usesLanguageCorrection = true
    let manejador = VNImageRequestHandler(cgImage: cg, options: [:])
    do {
        try manejador.perform([peticion])
        for observacion in peticion.results ?? [] {
            if let candidato = observacion.topCandidates(1).first {
                print(candidato.string)
            }
        }
    } catch {
        print("###ERROR:\(error.localizedDescription)")
    }
}
