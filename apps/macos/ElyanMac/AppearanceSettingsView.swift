import SwiftUI

/// Görünüm ve tema ayarları — mobil'in AppearanceSettings sayfasına karşılık gelir.
struct AppearanceSettingsView: View {
    @AppStorage("colorScheme") private var storedScheme: String = "system"
    @AppStorage("preferredLanguage") private var preferredLanguage: String = "tr"
    @AppStorage("chatFontSize") private var chatFontSize: Double = 14
    @AppStorage("showTimestamps") private var showTimestamps: Bool = false
    @AppStorage("compactBubbles") private var compactBubbles: Bool = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {

                // Tema
                settingsGroup(title: "Tema") {
                    VStack(spacing: 12) {
                        ForEach(SchemeOption.allCases) { option in
                            Button {
                                storedScheme = option.rawValue
                                applyScheme(option)
                            } label: {
                                HStack {
                                    Image(systemName: option.icon)
                                        .frame(width: 28)
                                        .foregroundStyle(storedScheme == option.rawValue ? .white : .primary)
                                    Text(option.label)
                                        .foregroundStyle(storedScheme == option.rawValue ? .white : .primary)
                                    Spacer()
                                    if storedScheme == option.rawValue {
                                        Image(systemName: "checkmark")
                                            .foregroundStyle(.white)
                                    }
                                }
                                .padding(.horizontal, 14)
                                .padding(.vertical, 10)
                                .background(storedScheme == option.rawValue ? Color.accentColor : Color.secondary.opacity(0.08))
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                // Sohbet Ayarları
                settingsGroup(title: "Sohbet") {
                    VStack(spacing: 14) {
                        HStack {
                            Text("Yazı Boyutu")
                            Spacer()
                            Text("\(Int(chatFontSize))pt")
                                .foregroundStyle(.secondary)
                                .monospacedDigit()
                        }
                        Slider(value: $chatFontSize, in: 11...20, step: 1)
                            .tint(.accentColor)

                        Divider()

                        Toggle("Saat Damgalarını Göster", isOn: $showTimestamps)
                        Toggle("Kompakt Balonlar", isOn: $compactBubbles)
                    }
                }

                // Dil
                settingsGroup(title: "Dil") {
                    Picker("", selection: $preferredLanguage) {
                        Text("Türkçe").tag("tr")
                        Text("English").tag("en")
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
            }
            .padding(24)
        }
        .navigationTitle("Görünüm")
        .onAppear { applyScheme(SchemeOption(rawValue: storedScheme) ?? .system) }
    }

    private func settingsGroup<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title.uppercased())
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.leading, 4)
            content()
        }
    }

    private func applyScheme(_ option: SchemeOption) {
        guard let app = NSApplication.shared.windows.first else { return }
        switch option {
        case .light: app.appearance = NSAppearance(named: .aqua)
        case .dark: app.appearance = NSAppearance(named: .darkAqua)
        case .system: app.appearance = nil
        }
    }
}

enum SchemeOption: String, CaseIterable, Identifiable {
    case system, light, dark
    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: return "Sistem"
        case .light: return "Açık"
        case .dark: return "Koyu"
        }
    }
    var icon: String {
        switch self {
        case .system: return "circle.lefthalf.filled"
        case .light: return "sun.max.fill"
        case .dark: return "moon.fill"
        }
    }
}
