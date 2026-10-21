// Localización de la página y orientación del texto con el framework Vision de macOS.
// Uso: swift vision_pagina.swift cuadro <imagen> [imagen...]
//        por cada imagen imprime "###FILE:<ruta>" y una línea "x1 y1 x2 y2 x3 y3 x4 y4" con las
//        esquinas del documento en píxeles (arriba-izq, arriba-der, abajo-der, abajo-izq), o "###ERROR:…"
//      swift vision_pagina.swift orientacion <imagen> [imagen...]
//        imprime los grados (0, 90, 180 o 270) que hay que girar las imágenes en sentido horario
//        para que el texto quede derecho: la orientación en la que Vision lee más texto, sumando
//        todas las imágenes dadas para que una página casi vacía no decida sola
import Foundation
import Vision
import AppKit

let argumentos = CommandLine.arguments
guard argumentos.count >= 3 else {
    FileHandle.standardError.write("uso: swift vision_pagina.swift cuadro|orientacion imagen...\n".data(using: .utf8)!)
    exit(1)
}

func abrir(_ ruta: String) -> CGImage? {
    guard let imagen = NSImage(contentsOfFile: ruta) else { return nil }
    return imagen.cgImage(forProposedRect: nil, context: nil, hints: nil)
}

if argumentos[1] == "cuadro" {
    for ruta in argumentos.dropFirst(2) {
        print("###FILE:\(ruta)")
        guard let cg = abrir(ruta) else { print("###ERROR:no se pudo abrir la imagen"); continue }
        let peticion = VNDetectDocumentSegmentationRequest()
        let manejador = VNImageRequestHandler(cgImage: cg, options: [:])
        do {
            try manejador.perform([peticion])
            guard let doc = peticion.results?.first else { print("###ERROR:sin documento"); continue }
            let w = CGFloat(cg.width), h = CGFloat(cg.height)
            // Vision devuelve coordenadas normalizadas con el origen abajo a la izquierda
            let puntos = [doc.topLeft, doc.topRight, doc.bottomRight, doc.bottomLeft]
            print(puntos.map { String(format: "%.1f %.1f", $0.x * w, (1 - $0.y) * h) }.joined(separator: " "))
        } catch {
            print("###ERROR:\(error.localizedDescription)")
        }
    }
} else if argumentos[1] == "orientacion" {
    let imagenes = argumentos.dropFirst(2).compactMap(abrir)
    guard !imagenes.isEmpty else { print("###ERROR:no se pudo abrir ninguna imagen"); exit(1) }
    // la orientación EXIF dice cómo está girada la imagen; para cada una se cuenta
    // cuánto texto reconoce Vision, ponderado por su confianza
    let candidatas: [(Int, CGImagePropertyOrientation)] = [(0, .up), (90, .right), (180, .down), (270, .left)]
    var mejor = (grados: 0, puntos: -1.0)
    for (grados, orientacion) in candidatas {
        var puntos = 0.0
        for cg in imagenes {
            let peticion = VNRecognizeTextRequest()
            peticion.recognitionLevel = .fast
            peticion.usesLanguageCorrection = false
            let manejador = VNImageRequestHandler(cgImage: cg, orientation: orientacion, options: [:])
            guard (try? manejador.perform([peticion])) != nil else { continue }
            for observacion in peticion.results ?? [] {
                if let candidato = observacion.topCandidates(1).first {
                    puntos += Double(candidato.string.count) * Double(candidato.confidence)
                }
            }
        }
        if puntos > mejor.puntos { mejor = (grados, puntos) }
    }
    print(mejor.grados)
} else {
    FileHandle.standardError.write("modo desconocido: \(argumentos[1])\n".data(using: .utf8)!)
    exit(1)
}
