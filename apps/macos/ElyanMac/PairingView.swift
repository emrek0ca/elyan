import SwiftUI
import CoreImage.CIFilterBuiltins

/// Masaüstü eşleştirme ekranı — mobil uygulamanın PairingScreen'ine karşılık gelir.
/// Backend'deki /v1/pairing/* endpoint'leri üzerinden QR kodu gösterir ve
/// claim (talep) durumunu poll ederek eşleştirme tamamlanınca bildirir.
struct PairingView: View {
    @EnvironmentObject var appState: AppState
    @State private var pairingCode: String = ""
    @State private var pairingSessionId: String = ""
    @State private var pairingToken: String = ""
    @State private var pairingQrText: String = ""
    @State private var isLoading = false
    @State private var isClaimed = false
    @State private var claimInfo: String = ""
    @State private var error: String = ""
    @State private var pollTask: Task<Void, Never>? = nil
    @State private var devices: [ElyanDevice] = []
    @State private var isLoadingDevices = false
    @State private var confirmRemove: ElyanDevice? = nil
    @State private var tab: Tab = .pair

    enum Tab { case pair, devices }

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                Text("Eşleştir").tag(Tab.pair)
                Text("Cihazlar").tag(Tab.devices)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 24)
            .padding(.top, 16)

            if tab == .pair {
                pairTab
            } else {
                devicesTab
            }
        }
        .onChange(of: tab) { _, newValue in loadForTab(newValue) }
        .task { loadForTab(tab) }
        .onDisappear { pollTask?.cancel() }
        .navigationTitle("Masaüstü Eşleştirme")
    }

    // MARK: - Pair Tab

    private var pairTab: some View {
        ScrollView {
            VStack(spacing: 28) {
                // Instructions
                VStack(spacing: 12) {
                    Image(systemName: "iphone.and.arrow.forward.outward")
                        .font(.system(size: 52))
                        .foregroundStyle(.tint)
                        .symbolEffect(.bounce, value: pairingCode)
                    Text("Mobil uygulama ile eşleştir")
                        .font(.title2.bold())
                    Text("Elyan mobil uygulamasını açın → Ayarlar → Masaüstü Bağlantısı → QR Kod Tara")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 360)
                }
                .padding(.top, 20)

                // QR or state
                if isLoading && pairingCode.isEmpty {
                    ProgressView("Bağlantı kodu oluşturuluyor…")
                        .frame(width: 200, height: 200)
                } else if isClaimed {
                    VStack(spacing: 16) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 72))
                            .foregroundStyle(.green)
                            .symbolEffect(.bounce, value: isClaimed)
                        Text("Eşleştirme tamamlandı!")
                            .font(.title3.bold())
                        if !claimInfo.isEmpty {
                            Text(claimInfo)
                                .foregroundStyle(.secondary)
                                .font(.callout)
                        }
                    }
                    .transition(.scale.combined(with: .opacity))
                } else if pairingCode.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "link.badge.plus")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        if !error.isEmpty {
                            Text(error)
                                .font(.callout)
                                .foregroundStyle(.red)
                                .multilineTextAlignment(.center)
                                .frame(maxWidth: 320)
                        }
                        Button("Kod Oluştur") { Task { await createPairingCode() } }
                            .buttonStyle(.borderedProminent)
                    }
                    .padding(20)
                } else {
                    VStack(spacing: 16) {
                        // QR Code — use the deep-link the backend built
                        // (`elyan://pair?sessionId=…&pairingCode=…`) so the
                        // mobile scanner receives both fields at once.
                        if let qrImage = generateQRCode(from: pairingQrText.isEmpty ? pairingCode : pairingQrText) {
                            Image(qrImage, scale: 1, label: Text("QR Kod"))
                                .interpolation(.none)
                                .resizable()
                                .frame(width: 200, height: 200)
                                .padding(12)
                                .background(Color.white)
                                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                                .shadow(color: .black.opacity(0.1), radius: 8, x: 0, y: 4)
                        }

                        // Pairing code text
                        VStack(spacing: 8) {
                            Text("Kod")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(pairingCode)
                                .font(.system(.title2, design: .monospaced).bold())
                                .textSelection(.enabled)
                                .padding(.horizontal, 16)
                                .padding(.vertical, 10)
                                .background(Color.secondary.opacity(0.1))
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            Button {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(pairingCode, forType: .string)
                            } label: {
                                Label("Kopyala", systemImage: "doc.on.doc")
                                    .font(.caption)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        }

                        // Poll indicator
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Mobil uygulama bekleniyor…")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.top, 4)
                    }
                    .transition(.opacity.combined(with: .scale))
                    .animation(.spring(response: 0.4, dampingFraction: 0.8), value: pairingCode)
                }

                if !isClaimed {
                    Button(pairingCode.isEmpty ? "Kod Oluştur" : "Yeni Kod Oluştur") {
                        Task { await createPairingCode() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading)
                }
            }
            .padding(24)
        }
    }

    // MARK: - Devices Tab

    private var devicesTab: some View {
        Group {
            if isLoadingDevices && devices.isEmpty {
                ProgressView()
                    .padding(.top, 60)
                Spacer()
            } else if devices.isEmpty {
                VStack(spacing: 16) {
                    Image(systemName: "desktopcomputer.and.arrow.down")
                        .font(.system(size: 48))
                        .foregroundStyle(.secondary)
                    Text("Eşleştirilmiş cihaz yok")
                        .font(.headline)
                    Text("QR kod ile bir cihaz ekleyin.")
                        .foregroundStyle(.secondary)
                        .font(.callout)
                }
                .padding(40)
                Spacer()
            } else {
                List(devices) { device in
                    HStack(spacing: 14) {
                        Image(systemName: platformIcon(device.platform))
                            .font(.system(size: 28))
                            .foregroundStyle(.tint)
                            .frame(width: 44)

                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(device.name)
                                    .font(.body.weight(.medium))
                                if device.isCurrentDevice {
                                    Text("Bu cihaz")
                                        .font(.caption2.weight(.medium))
                                        .padding(.horizontal, 6)
                                        .padding(.vertical, 2)
                                        .background(Color.green.opacity(0.15))
                                        .foregroundStyle(.green)
                                        .clipShape(Capsule())
                                }
                            }
                            Text(device.platform.uppercased())
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if let lastSeen = device.lastSeenAt {
                                Text("Son görülme: \(lastSeen.formatted(.relative(presentation: .named)))")
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                            }
                        }

                        Spacer()

                        if !device.isCurrentDevice {
                            Button {
                                confirmRemove = device
                            } label: {
                                Image(systemName: "trash")
                                    .foregroundStyle(.red)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 6)
                }
            }
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await loadDevices() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(isLoadingDevices)
            }
        }
        .confirmationDialog(
            "Bu cihazı kaldırmak istediğine emin misin?",
            isPresented: Binding(get: { confirmRemove != nil }, set: { if !$0 { confirmRemove = nil } }),
            titleVisibility: .visible
        ) {
            Button("Kaldır", role: .destructive) {
                if let d = confirmRemove { Task { await removeDevice(d) } }
            }
            Button("İptal", role: .cancel) { confirmRemove = nil }
        }
    }

    // MARK: - Actions

    private func loadForTab(_ tab: Tab) {
        switch tab {
        case .pair:
            if pairingCode.isEmpty { Task { await createPairingCode() } }
        case .devices:
            Task { await loadDevices() }
        }
    }

    private func createPairingCode() async {
        pollTask?.cancel()
        pairingCode = ""
        pairingSessionId = ""
        pairingToken = ""
        pairingQrText = ""
        isClaimed = false
        claimInfo = ""
        error = ""
        isLoading = true

        do {
            // Backend contract: POST /v1/pairing/sessions returns
            //   { sessionId, pairingCode, pairingToken, qrText, qrPayload, ... }
            // Body requires deviceLabel + platform (createPairSessionBodySchema),
            // otherwise it 400s with "deviceLabel: Required · platform: Required".
            // The pairingToken is required by GET /sessions/:sessionId via the
            // x-pairing-token header, so we hold on to it for polling.
            let hostName = Host.current().localizedName ?? "Elyan Mac"
            let raw = try await appState.backend.postJSON(
                path: "/v1/pairing/sessions",
                body: [
                    "deviceLabel": hostName,
                    "platform": "macos",
                    "runtimeVersion": "1.0.0"
                ],
                requireAuth: true
            )
            let payload = ElyanBackend.unwrap(raw)
            pairingSessionId = (payload["sessionId"] as? String) ?? ""
            pairingCode = (payload["pairingCode"] as? String)
                ?? (payload["manualEntryCode"] as? String)
                ?? ""
            pairingToken = (payload["pairingToken"] as? String) ?? ""
            pairingQrText = (payload["qrText"] as? String) ?? ""

            if pairingSessionId.isEmpty || pairingCode.isEmpty || pairingToken.isEmpty {
                error = "Sunucu geçerli bir eşleştirme oturumu döndürmedi."
            } else {
                appState.backend.invalidateGetCache()
                startPolling()
            }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        isLoading = false
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled && !isClaimed {
                try? await Task.sleep(nanoseconds: 3_000_000_000) // 3 sn
                guard !Task.isCancelled else { break }
                if let claimed = await checkPairingClaim() {
                    await MainActor.run {
                        withAnimation {
                            isClaimed = true
                            claimInfo = claimed
                        }
                    }
                    await loadDevices()
                    break
                }
            }
        }
    }

    private func checkPairingClaim() async -> String? {
        guard !pairingSessionId.isEmpty, !pairingToken.isEmpty else { return nil }
        do {
            // Backend: GET /v1/pairing/sessions/:sessionId  (auth NOT required —
            // pairing token in header authenticates the poll). Status is a plain
            // string ("pending" / "claimed" / "expired"), not a boolean flag.
            let raw = try await appState.backend.internalGetJSON(
                path: "/v1/pairing/sessions/\(pairingSessionId)",
                queryItems: [],
                requireAuth: false,
                cacheTTL: 0,
                extraHeaders: ["x-pairing-token": pairingToken]
            )
            let payload = ElyanBackend.unwrap(raw)
            let status = (payload["status"] as? String) ?? ""
            if status.lowercased() == "claimed" {
                // Backend hands us runtimeAuth = {deviceId, deviceSecret} the
                // moment the mobile side claims. Register the runtime right
                // away so mobile immediately sees this desktop as online
                // instead of "eşleştirildi ama çevrimdışı" purgatory.
                if let runtimeAuth = payload["runtimeAuth"] as? [String: Any],
                   let deviceId = runtimeAuth["deviceId"] as? String,
                   let deviceSecret = runtimeAuth["deviceSecret"] as? String,
                   !deviceId.isEmpty, !deviceSecret.isEmpty {
                    _ = try? await appState.backend.registerRuntime(
                        deviceId: deviceId,
                        deviceSecret: deviceSecret
                    )
                    await appState.backend.runtimeHeartbeat(status: "online")
                }
                let mobile = payload["mobileDevice"] as? [String: Any] ?? [:]
                let deviceName = (mobile["displayName"] as? String)
                    ?? (mobile["name"] as? String)
                    ?? (payload["deviceName"] as? String)
                    ?? ""
                return deviceName.isEmpty
                    ? "Cihaz başarıyla eşleştirildi."
                    : "\(deviceName) eşleştirildi."
            }
        } catch { }
        return nil
    }

    private func loadDevices() async {
        isLoadingDevices = true
        do {
            devices = try await appState.backend.getDevices()
        } catch {
            // silent fail — cihaz listesi yüklenemezse log'a not düş
        }
        isLoadingDevices = false
    }

    private func removeDevice(_ device: ElyanDevice) async {
        do {
            try await appState.backend.removeDevice(deviceId: device.id)
            devices.removeAll { $0.id == device.id }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - Helpers

    private func generateQRCode(from string: String) -> CGImage? {
        let context = CIContext()
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(string.utf8)
        filter.correctionLevel = "M"
        guard let outputImage = filter.outputImage else { return nil }
        let transform = CGAffineTransform(scaleX: 10, y: 10)
        let scaled = outputImage.transformed(by: transform)
        return context.createCGImage(scaled, from: scaled.extent)
    }

    private func platformIcon(_ platform: String) -> String {
        switch platform.lowercased() {
        case "windows": return "pc"
        case "linux": return "terminal"
        default: return "desktopcomputer"
        }
    }
}
