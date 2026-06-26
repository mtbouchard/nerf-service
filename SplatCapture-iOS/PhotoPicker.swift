import SwiftUI
import PhotosUI
import UIKit

/// Library import via PHPickerViewController. Works on device and in the Simulator,
/// and needs no photo-library permission (the picker runs out of process).
struct PhotoPicker: UIViewControllerRepresentable {
    /// Called once with the selected images, in selection order.
    let onComplete: ([UIImage]) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration()
        config.filter = .images
        config.selectionLimit = 0 // 0 == no limit
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    class Coordinator: NSObject, PHPickerViewControllerDelegate {
        private let parent: PhotoPicker

        init(_ parent: PhotoPicker) {
            self.parent = parent
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            guard !results.isEmpty else {
                parent.onComplete([])
                return
            }

            // Loads are async; keep a fixed-size slot array so the final order matches selection.
            var images = [UIImage?](repeating: nil, count: results.count)
            let group = DispatchGroup()

            for (index, result) in results.enumerated() {
                guard result.itemProvider.canLoadObject(ofClass: UIImage.self) else { continue }
                group.enter()
                result.itemProvider.loadObject(ofClass: UIImage.self) { object, _ in
                    if let image = object as? UIImage {
                        images[index] = image
                    }
                    group.leave()
                }
            }

            group.notify(queue: .main) {
                self.parent.onComplete(images.compactMap { $0 })
            }
        }
    }
}
