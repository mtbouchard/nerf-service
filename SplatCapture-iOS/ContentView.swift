import SwiftUI
import AVFoundation

struct ContentView: View {
    @StateObject private var cameraService = CameraService()
    @StateObject private var viewModel = MainViewModel()
    
    @State private var showReviewGrid = false
    @State private var showSettings = false
    @State private var showShareSheet = false
    
    // Aesthetic color scheme
    let darkBackground = Color(red: 13/255, green: 14/255, blue: 20/255)
    let accentPurple = Color(red: 124/255, green: 58/255, blue: 237/255)
    let subtleGray = Color(red: 30/255, green: 30/255, blue: 40/255)
    
    var body: some View {
        Z_Stack_With_Custom_Color_Background()
    }
    
    // Container helper to make ZStack readable
    @ViewBuilder
    private func Z_Stack_With_Custom_Color_Background() -> some View {
        ZStack {
            darkBackground.ignoresSafeArea()
            
            if viewModel.activeJobState == .done, let viewerURL = viewModel.viewerURL {
                // Interactive 3D Viewing Stage
                VStack(spacing: 0) {
                    HStack {
                        Button(action: { viewModel.reset() }) {
                            HStack {
                                Image(systemName: "camera")
                                Text("New Scan")
                            }
                            .foregroundColor(.white)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(subtleGray)
                            .cornerRadius(20)
                        }
                        
                        Spacer()
                        
                        Text("3D RECONSTRUCTION")
                            .font(.system(size: 14, weight: .bold, design: .monospaced))
                            .foregroundColor(.gray)
                        
                        Spacer()
                        
                        Button(action: { showShareSheet = true }) {
                            Image(systemName: "square.and.arrow.up")
                                .font(.title3)
                                .foregroundColor(.white)
                                .padding(10)
                                .background(subtleGray)
                                .cornerRadius(50)
                        }
                    }
                    .padding()
                    .background(darkBackground)
                    
                    WebViewer(url: viewerURL)
                        .ignoresSafeArea(edges: .bottom)
                }
                .sheet(isPresented: $showShareSheet) {
                    let base = viewModel.serverURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                    if let rawResultURL = URL(string: "\(base)/jobs/\(viewModel.jobId ?? "")/result") {
                        ShareSheet(activityItems: [rawResultURL, "Check out my 3D Gaussian Splat model generated from my iPhone!"])
                    }
                }
            } else {
                // Main Camera Feed / Capture Screen
                VStack(spacing: 0) {
                    // Header Bar
                    HStack {
                        Button(action: { showSettings = true }) {
                            Image(systemName: "gearshape")
                                .font(.title3)
                                .foregroundColor(.white)
                        }
                        
                        Spacer()
                        
                        Text("SPLAT CAPTURE")
                            .font(.system(size: 16, weight: .bold, design: .monospaced))
                            .foregroundColor(accentPurple)
                        
                        Spacer()
                        
                        // Indicators
                        HStack(spacing: 6) {
                            Circle()
                                .fill(viewModel.backend == "runpod" ? Color.green : Color.blue)
                                .frame(width: 8, height: 8)
                            Text(viewModel.backend.uppercased())
                                .font(.system(size: 11, weight: .bold, design: .monospaced))
                                .foregroundColor(.gray)
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(subtleGray)
                        .cornerRadius(12)
                    }
                    .padding()
                    
                    // Live Viewfinder viewport
                    ZStack {
                        if cameraService.isPermissionGranted {
                            CameraPreviewView(session: cameraService.session)
                                .cornerRadius(24)
                                .padding(.horizontal, 12)
                                .shadow(color: Color.black.opacity(0.4), radius: 10)
                        } else {
                            RoundedRectangle(cornerRadius: 24)
                                .fill(subtleGray)
                                .padding(.horizontal, 12)
                                .overlay(
                                    VStack(spacing: 12) {
                                        Image(systemName: "camera.fill")
                                            .font(.largeTitle)
                                        Text("Camera Permission Required")
                                            .font(.headline)
                                        Button(action: { cameraService.checkPermissions() }) {
                                            Text("Grant Access")
                                                .fontWeight(.bold)
                                                .padding(.horizontal, 18)
                                                .padding(.vertical, 10)
                                                .background(accentPurple)
                                                .cornerRadius(15)
                                        }
                                    }
                                    .foregroundColor(.white)
                                )
                        }
                        
                        // Real-time circular guidelines overlay for standard capture
                        Circle()
                            .stroke(Color.white.opacity(0.15), style: StrokeStyle(lineWidth: 1.5, dash: [6, 6]))
                            .frame(width: 250, height: 250)
                            .allowsHitTesting(false)
                        
                        // Photos counter badge
                        VStack {
                            HStack {
                                Spacer()
                                Text("\(viewModel.stagedImages.count) Staged")
                                    .font(.system(size: 14, weight: .semibold, design: .monospaced))
                                    .foregroundColor(.white)
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 8)
                                    .background(Color.black.opacity(0.6))
                                    .cornerRadius(18)
                                    .padding(24)
                            }
                            Spacer()
                        }
                    }
                    
                    // Bottom Controls Bar
                    HStack(spacing: 40) {
                        // Thumbnail review grid drawer button
                        Button(action: { showReviewGrid = true }) {
                            ZStack {
                                RoundedRectangle(cornerRadius: 12)
                                    .fill(subtleGray)
                                    .frame(width: 50, height: 50)
                                
                                if let latest = viewModel.stagedImages.last {
                                    Image(uiImage: latest.image)
                                        .resizable()
                                        .aspectRatio(contentMode: .fill)
                                        .frame(width: 50, height: 50)
                                        .cornerRadius(12)
                                } else {
                                    Image(systemName: "photo.on.rectangle.angled")
                                        .foregroundColor(.white)
                                }
                            }
                        }
                        .disabled(viewModel.stagedImages.isEmpty)
                        
                        // Shutter Button with circular load guide
                        Button(action: {
                            cameraService.capturePhoto()
                        }) {
                            ZStack {
                                Circle()
                                    .fill(Color.white)
                                    .frame(width: 72, height: 72)
                                Circle()
                                    .stroke(accentPurple, lineWidth: 3)
                                    .frame(width: 82, height: 82)
                            }
                        }
                        .disabled(!cameraService.isSessionRunning)
                        
                        // Quick Action button triggers Reconstruction sheet
                        Button(action: {
                            viewModel.startReconstruction()
                        }) {
                            ZStack {
                                Circle()
                                    .fill(viewModel.stagedImages.count >= 3 ? accentPurple : subtleGray)
                                    .frame(width: 50, height: 50)
                                Image(systemName: "bolt.fill")
                                    .foregroundColor(.white)
                            }
                        }
                        .disabled(viewModel.stagedImages.count < 3)
                    }
                    .padding(.vertical, 32)
                }
            }
            
            // Uploading & Processing Progress Modal HUD Overlays
            if viewModel.isProcessing {
                ZStack {
                    Color.black.opacity(0.85)
                        .ignoresSafeArea()
                    
                    VStack(spacing: 24) {
                        if viewModel.activeJobState == .uploading {
                            // Circular upload loader
                            ZStack {
                                Circle()
                                    .stroke(Color.white.opacity(0.1), lineWidth: 6)
                                    .frame(width: 120, height: 120)
                                Circle()
                                    .stroke(accentPurple, style: StrokeStyle(lineWidth: 6, lineCap: .round))
                                    .rotationEffect(.degrees(-90))
                                    .frame(width: 120, height: 120)
                                    .animation(.easeOut, value: viewModel.uploadProgress)
                                
                                Text("\(Int(viewModel.uploadProgress * 100))%")
                                    .font(.system(size: 24, weight: .bold, design: .monospaced))
                                    .foregroundColor(.white)
                            }
                            
                            Text("Uploading Frame Assets...")
                                .font(.headline)
                                .foregroundColor(.white)
                            
                        } else {
                            // Long polling infinite progress loader
                            VStack(spacing: 16) {
                                ProgressView()
                                    .progressViewStyle(CircularProgressViewStyle(tint: accentPurple))
                                    .scaleEffect(1.5)
                                    .padding(.bottom, 8)
                                
                                Text(viewModel.activeJobState.rawValue)
                                    .font(.headline)
                                    .foregroundColor(.white)
                                
                                if !viewModel.jobStatusText.isEmpty {
                                    Text(viewModel.jobStatusText)
                                        .font(.subheadline)
                                        .foregroundColor(.gray)
                                        .multilineTextAlignment(.center)
                                        .padding(.horizontal)
                                }
                            }
                        }
                        
                        Button(action: { viewModel.reset() }) {
                            Text("Cancel Scan")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                                .padding(.horizontal, 20)
                                .padding(.vertical, 10)
                                .background(subtleGray)
                                .cornerRadius(15)
                        }
                        .padding(.top, 24)
                    }
                }
            }
            
            // Error Message Banner pop-up
            if let errorMessage = viewModel.errorMessage {
                VStack {
                    Spacer()
                    HStack(spacing: 12) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(.yellow)
                        Text(errorMessage)
                            .font(.subheadline)
                            .foregroundColor(.white)
                        Spacer()
                        Button(action: { viewModel.errorMessage = nil }) {
                            Image(systemName: "xmark")
                                .foregroundColor(.gray)
                        }
                    }
                    .padding()
                    .background(Color.red.opacity(0.85))
                    .cornerRadius(12)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
                }
            }
        }
        .onReceive(cameraService.photoCaptured) { image in
            viewModel.addImage(image)
        }
        .task {
            await viewModel.refreshHealth()
        }
        .sheet(isPresented: $showReviewGrid) {
            ReviewGridView(viewModel: viewModel)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(viewModel: viewModel)
        }
    }
}

// Interactive Review and Outlier Culling Grid sheet
struct ReviewGridView: View {
    @ObservedObject var viewModel: MainViewModel
    @Environment(\.dismiss) var dismiss
    
    let columns = [
        GridItem(.adaptive(minimum: 90))
    ]
    
    var body: some View {
        NavigationView {
            ZStack {
                Color(red: 13/255, green: 14/255, blue: 20/255).ignoresSafeArea()
                
                ScrollView {
                    LazyVGrid(columns: columns, spacing: 12) {
                        ForEach(viewModel.stagedImages) { item in
                            ZStack(alignment: .topTrailing) {
                                Image(uiImage: item.image)
                                    .resizable()
                                    .aspectRatio(contentMode: .fill)
                                    .frame(width: 95, height: 95)
                                    .cornerRadius(12)
                                    .clipped()
                                
                                Button(action: {
                                    viewModel.removeImage(withId: item.id)
                                }) {
                                    Image(systemName: "minus.circle.fill")
                                        .foregroundColor(.red)
                                        .background(Circle().fill(Color.black))
                                }
                                .padding(4)
                            }
                        }
                    }
                    .padding()
                }
                .navigationTitle("Staged Photos (\(viewModel.stagedImages.count))")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button("Close") { dismiss() }
                            .foregroundColor(.white)
                    }
                    
                    ToolbarItem(placement: .bottomBar) {
                        Button(action: {
                            dismiss()
                            viewModel.startReconstruction()
                        }) {
                            Text("Reconstruct Scan")
                                .fontWeight(.bold)
                                .foregroundColor(.white)
                                .padding(.horizontal, 40)
                                .padding(.vertical, 12)
                                .background(viewModel.stagedImages.count >= 3 ? Color(red: 124/255, green: 58/255, blue: 237/255) : Color.gray)
                                .cornerRadius(24)
                        }
                        .disabled(viewModel.stagedImages.count < 3)
                    }
                }
            }
            .preferredColorScheme(.dark)
        }
    }
}

// In-app Settings Sheet for URLs and Backends selection
struct SettingsView: View {
    @ObservedObject var viewModel: MainViewModel
    @Environment(\.dismiss) var dismiss
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Endpoint Configuration")) {
                    TextField("Server URL", text: $viewModel.serverURL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                }
                
                Section(header: Text("Server Backend")) {
                    Text("Compute backend is configured on the server (NERF_BACKEND env var), not in the app. Tap Refresh to read /healthz.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                    HStack {
                        Text("Reported backend")
                        Spacer()
                        Text(viewModel.backend.uppercased())
                            .font(.system(.body, design: .monospaced))
                    }
                    Button("Refresh from /healthz") {
                        Task { await viewModel.refreshHealth() }
                    }
                }
            }
            .navigationTitle("Scanner Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundColor(.blue)
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}

// SwiftUI Camera preview view wrapper of AVCaptureVideoPreviewLayer
struct CameraPreviewView: UIViewRepresentable {
    let session: AVCaptureSession
    
    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: UIScreen.main.bounds)
        let previewLayer = AVCaptureVideoPreviewLayer(session: session)
        previewLayer.frame = view.bounds
        previewLayer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(previewLayer)
        return view
    }
    
    func updateUIView(_ uiView: UIView, context: Context) {
        if let sublayers = uiView.layer.sublayers {
            for layer in sublayers {
                if let previewLayer = layer as? AVCaptureVideoPreviewLayer {
                    previewLayer.frame = uiView.bounds
                }
            }
        }
    }
}

// UIKit native iOS Share Sheet bridge
struct ShareSheet: UIViewControllerRepresentable {
    let activityItems: [Any]
    
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: nil)
    }
    
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
