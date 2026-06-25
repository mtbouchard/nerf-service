import Foundation
import UIKit
import Combine

struct IdentifiableImage: Identifiable {
    let id = UUID()
    let image: UIImage
}

enum JobState: String {
    case idle = "Idle"
    case uploading = "Uploading Photos"
    case nerfifying = "Submitting Job"
    case polling = "Processing on GPU (Tiling/COLMAP/Splat)"
    case done = "Done"
    case failed = "Failed"
}

class MainViewModel: ObservableObject {
    @Published var serverURL: String = "https://nerf.mattbouchard.com"
    // Informational only — the server's NERF_BACKEND env var selects the compute path.
    // Check GET /healthz to see which backend is actually running.
    @Published var backend: String = "runpod"
    
    @Published var stagedImages: [IdentifiableImage] = []
    @Published var isProcessing: Bool = false
    @Published var uploadProgress: Float = 0.0
    @Published var activeJobState: JobState = .idle
    @Published var jobId: String? = nil
    @Published var jobStatusText: String = ""
    @Published var viewerURL: URL? = nil
    @Published var errorMessage: String? = nil
    
    private var cancellables = Set<AnyCancellable>()
    private var timer: Timer? = nil
    
    func reset() {
        stagedImages.removeAll()
        isProcessing = false
        uploadProgress = 0.0
        activeJobState = .idle
        jobId = nil
        jobStatusText = ""
        viewerURL = nil
        errorMessage = nil
        timer?.invalidate()
        timer = nil
    }
    
    func addImage(_ image: UIImage) {
        // Enforce maximum images to prevent accidental resource exhaustion on server (e.g. max 80)
        if stagedImages.count < 80 {
            stagedImages.append(IdentifiableImage(image: image))
        }
    }
    
    func removeImage(withId id: UUID) {
        stagedImages.removeAll { $0.id == id }
    }

    /// Read GET /healthz so the UI shows the server's actual NERF_BACKEND.
    func refreshHealth() async {
        guard let url = URL(string: "\(baseURL)/healthz") else { return }
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let reported = json["backend"] as? String else { return }
            await MainActor.run { self.backend = reported }
        } catch {
            await MainActor.run {
                self.errorMessage = "Could not reach server: \(error.localizedDescription)"
            }
        }
    }
    
    // Core networking flow
    func startReconstruction() {
        guard stagedImages.count >= 3 else {
            self.errorMessage = "A minimum of 3 overlapping photos is required for reconstruction."
            return
        }
        
        isProcessing = true
        activeJobState = .uploading
        uploadProgress = 0.0
        errorMessage = nil
        
        Task {
            do {
                // Step 1: Upload all images in parallel
                let imageIds = try await uploadStagedImages()
                
                // Step 2: Trigger NeRFify endpoint
                await MainActor.run { self.activeJobState = .nerfifying }
                let jobId = try await triggerNerfify(imageIds: imageIds)
                
                await MainActor.run {
                    self.jobId = jobId
                    self.activeJobState = .polling
                }
                
                // Step 3: Start polling for status
                try await startPolling(jobId: jobId)
                
            } catch {
                await MainActor.run {
                    self.errorMessage = error.localizedDescription
                    self.activeJobState = .failed
                    self.isProcessing = false
                }
            }
        }
    }
    
    // Step 1: Parallel multi-part upload (preserve capture order for downstream SfM)
    private func uploadStagedImages() async throws -> [String] {
        let imagesData = stagedImages.compactMap { $0.image.jpegData(compressionQuality: 0.8) }
        let totalCount = Float(imagesData.count)
        var completedCount: Float = 0.0

        return try await withThrowingTaskGroup(of: (Int, String).self) { group in
            for (index, data) in imagesData.enumerated() {
                group.addTask {
                    let imageId = try await self.uploadSingleImage(data: data, fileName: "frame_\(index).jpg")
                    return (index, imageId)
                }
            }

            var indexedIds = [(Int, String)]()
            for try await pair in group {
                indexedIds.append(pair)
                completedCount += 1.0
                await MainActor.run {
                    self.uploadProgress = completedCount / totalCount
                }
            }
            return indexedIds.sorted { $0.0 < $1.0 }.map(\.1)
        }
    }

    private var baseURL: String {
        serverURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }
    
    private func uploadSingleImage(data: Data, fileName: String) async throws -> String {
        guard let url = URL(string: "\(baseURL)/upload") else {
            throw URLError(.badURL)
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        
        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        
        let (responseData, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw NSError(domain: "UploadError", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to upload image \(fileName)"])
        }
        
        guard let json = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
              let imageId = json["id"] as? String else {
            throw NSError(domain: "UploadError", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid server response format"])
        }
        
        return imageId
    }
    
    // Step 2: POST /nerfify
    private func triggerNerfify(imageIds: [String]) async throws -> String {
        guard let url = URL(string: "\(baseURL)/nerfify") else {
            throw URLError(.badURL)
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let payload: [String: Any] = ["images": imageIds]
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        
        let (responseData, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        
        if httpResponse.statusCode != 202 {
            // Read details
            if let json = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
               let detail = json["detail"] as? String {
                throw NSError(domain: "NerfifyError", code: httpResponse.statusCode, userInfo: [NSLocalizedDescriptionKey: detail])
            }
            throw NSError(domain: "NerfifyError", code: httpResponse.statusCode, userInfo: [NSLocalizedDescriptionKey: "Server returned code \(httpResponse.statusCode)"])
        }
        
        guard let json = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
              let jobId = json["job_id"] as? String else {
            throw NSError(domain: "NerfifyError", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid nerfify response format"])
        }
        
        return jobId
    }
    
    // Step 3: Poll /jobs/{id} until done or failed (matches client/client.py)
    private func startPolling(jobId: String) async throws {
        let deadline = Date().addingTimeInterval(3600) // GPU jobs can take many minutes
        var isPolling = true

        while isPolling {
            if Date() > deadline {
                throw NSError(domain: "ProcessingFailed", code: 4,
                              userInfo: [NSLocalizedDescriptionKey: "Job timed out after 60 minutes"])
            }

            guard let url = URL(string: "\(baseURL)/jobs/\(jobId)") else {
                throw URLError(.badURL)
            }

            let (responseData, response) = try await URLSession.shared.data(for: url)
            guard let httpResponse = response as? HTTPURLResponse else {
                try await Task.sleep(nanoseconds: 5_000_000_000)
                continue
            }

            if httpResponse.statusCode == 404 {
                throw NSError(domain: "ProcessingFailed", code: 404,
                              userInfo: [NSLocalizedDescriptionKey: "Job not found — the server may have restarted"])
            }

            guard httpResponse.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
                  let statusStr = json["status"] as? String else {
                try await Task.sleep(nanoseconds: 5_000_000_000)
                continue
            }

            let resultFormat = json["result_format"] as? String

            await MainActor.run {
                self.jobStatusText = "Status: \(statusStr.uppercased())"
                if let errorMsg = json["error"] as? String {
                    self.jobStatusText += "\n\(errorMsg)"
                }
            }

            if statusStr == "done" {
                isPolling = false
                let viewerURL: URL?
                if resultFormat == "world" {
                    // World Labs backend: /result redirects to a navigable Marble world
                    viewerURL = URL(string: "\(baseURL)/jobs/\(jobId)/result")
                } else {
                    // RunPod/local: embed our WebGL PLY viewer
                    let resultPath = "\(baseURL)/jobs/\(jobId)/result"
                    var components = URLComponents(string: "\(baseURL)/viewer")!
                    components.queryItems = [URLQueryItem(name: "url", value: resultPath)]
                    viewerURL = components.url
                }

                await MainActor.run {
                    self.activeJobState = .done
                    self.viewerURL = viewerURL
                    self.isProcessing = false
                }
            } else if statusStr == "failed" {
                isPolling = false
                let errorMsg = json["error"] as? String ?? "Unknown reconstruction failure."
                throw NSError(domain: "ProcessingFailed", code: 3,
                              userInfo: [NSLocalizedDescriptionKey: errorMsg])
            } else {
                try await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }
}
