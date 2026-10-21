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

let salidaJSON = argumentos.contains("--json")
for ruta in argumentos.dropFirst(2).filter({ $0 != "--json" }) {
    print("###FILE:\(ruta)")
    guard let imagen = NSImage(contentsOfFile: ruta),
          let cg = imagen.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("###ERROR:no se pudo abrir la imagen")
        continue
    }
    let peticion = VNRecognizeTextRequest()
    peticion.recognitionLevel = .accurate
    peticion.minimumTextHeight = 0.0
    peticion.recognitionLanguages = idiomas
    peticion.usesLanguageCorrection = true
    let manejador = VNImageRequestHandler(cgImage: cg, options: [:])
    do {
        try manejador.perform([peticion])
        var lineas: [[String: Any]] = []
        for observacion in peticion.results ?? [] {
            if let candidato = observacion.topCandidates(1).first {
                if salidaJSON {
                    let caja = observacion.boundingBox
                    lineas.append(["texto": candidato.string, "confianza": candidato.confidence,
                                   "caja": [caja.origin.x, caja.origin.y, caja.width, caja.height]])
                } else {
                    print(candidato.string)
                }
            }
        }
        if salidaJSON {
            let datos = try JSONSerialization.data(withJSONObject: lineas, options: [.sortedKeys])
            print(String(data: datos, encoding: .utf8)!)
        }
    } catch {
        print("###ERROR:\(error.localizedDescription)")
    }
}
