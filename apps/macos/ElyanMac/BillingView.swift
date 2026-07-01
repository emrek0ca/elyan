import SwiftUI

struct BillingView: View {
    @EnvironmentObject var appState: AppState
    @State private var plans: [DesktopBillingPlan] = []
    @State private var summary: DesktopBillingSummary?
    @State private var billingProfile = DesktopBillingProfile.empty
    @State private var isLoading = false
    @State private var isLaunchingCheckout = false
    @State private var isSavingProfile = false
    @State private var error: String = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                if !billingProfile.isComplete {
                    profileCard
                }
                usageCard
                plansSection
            }
            .padding(24)
        }
        .navigationTitle("Abonelik")
        .task {
            guard summary == nil, !isLoading else { return }
            await reload()
        }
        .refreshable {
            await reload()
        }
    }

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Mevcut plan")
                .font(.headline)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(summary?.planLabel ?? "Yükleniyor")
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                if let status = summary?.statusLabel {
                    Text(status)
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Color.accentColor.opacity(0.12))
                        .foregroundStyle(.tint)
                        .clipShape(Capsule())
                }
            }
            if let hint = summary?.manageSubscriptionHint, !hint.isEmpty {
                Text(hint)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            if !error.isEmpty {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
            HStack(spacing: 10) {
                Button("Yenile") {
                    Task { await reload() }
                }
                .buttonStyle(.bordered)

                if let manageURL = summary?.manageURL {
                    Button("Aboneliği Yönet") {
                        NSWorkspace.shared.open(manageURL)
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var usageCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Kullanım")
                .font(.headline)
            HStack(spacing: 16) {
                usageMetric(
                    title: "Token",
                    used: summary?.tokensUsed ?? 0,
                    remaining: summary?.tokensRemaining ?? 0
                )
                usageMetric(
                    title: "Görev",
                    used: summary?.tasksUsed ?? 0,
                    remaining: summary?.tasksRemaining ?? 0
                )
                usageMetric(
                    title: "Masaüstü",
                    used: summary?.desktopCount ?? 0,
                    remaining: max(0, (summary?.desktopLimit ?? 0) - (summary?.desktopCount ?? 0))
                )
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var profileCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Fatura profili")
                .font(.headline)
            Text("Abonelik başlatmak için eksik bilgileri tamamla.")
                .font(.callout)
                .foregroundStyle(.secondary)

            if !billingProfile.missingFields.isEmpty {
                Text("Eksik alanlar: \(billingProfile.missingFields.joined(separator: ", "))")
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }

            Group {
                profileField("Ad Soyad", text: $billingProfile.fullName)
                profileField("E-posta", text: $billingProfile.email)
                profileField("Telefon", text: $billingProfile.phone)
                profileField("Kimlik / Vergi No", text: $billingProfile.identityNumber)
                profileField("Adres", text: $billingProfile.addressLine1)
                HStack(spacing: 12) {
                    profileField("Şehir", text: $billingProfile.city)
                    profileField("Ülke", text: $billingProfile.country)
                    profileField("Posta Kodu", text: $billingProfile.zipCode)
                }
            }

            Button {
                Task { await saveBillingProfile() }
            } label: {
                HStack(spacing: 8) {
                    if isSavingProfile {
                        ProgressView().controlSize(.small)
                    }
                    Text("Profili Kaydet")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSavingProfile || !billingProfile.canSubmit)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(Color.secondary.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var plansSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Planlar")
                .font(.headline)
            ForEach(plans) { plan in
                planCard(plan)
            }
        }
    }

    private func planCard(_ plan: DesktopBillingPlan) -> some View {
        let title = actionTitle(for: plan)
        let isDisabled = isLaunchingCheckout || (plan.isCurrent && summary?.manageURL == nil)

        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(plan.name)
                        .font(.title3.weight(.semibold))
                    Text(plan.priceLabel)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                actionButton(title: title, plan: plan, isDisabled: isDisabled)
            }

            if !plan.summary.isEmpty {
                Text(plan.summary)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            if !plan.highlights.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(plan.highlights, id: \.self) { item in
                        Label(item, systemImage: "checkmark")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(plan.isCurrent ? Color.accentColor.opacity(0.09) : Color.secondary.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    @ViewBuilder
    private func actionButton(title: String, plan: DesktopBillingPlan, isDisabled: Bool) -> some View {
        let button = Button(title) {
            Task { await startCheckout(for: plan) }
        }
        .disabled(isDisabled)

        if plan.isCurrent {
            button.buttonStyle(CurrentPlanButtonStyle())
        } else {
            button.buttonStyle(UpgradePlanButtonStyle())
        }
    }

    private func usageMetric(title: String, used: Int, remaining: Int) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("\(remaining)")
                .font(.title2.weight(.bold))
            Text("Kalan")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text("Kullanılan \(used)")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func profileField(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField(title, text: text)
                .textFieldStyle(.roundedBorder)
        }
    }

    private func actionTitle(for plan: DesktopBillingPlan) -> String {
        if plan.isCurrent {
            return summary?.manageURL == nil ? "Aktif" : "Yönet"
        }
        return plan.primaryActionLabel.isEmpty ? "Seç" : plan.primaryActionLabel
    }

    private func reload() async {
        isLoading = true
        error = ""
        defer { isLoading = false }
        do {
            async let plansTask = appState.backend.fetchBillingPlans()
            async let summaryTask = appState.backend.fetchBillingSummary()
            async let profileTask = appState.backend.fetchBillingProfile()
            let (loadedPlans, loadedSummary, loadedProfile) = try await (plansTask, summaryTask, profileTask)
            let currentCode = loadedSummary.planCode
            self.summary = loadedSummary
            self.billingProfile = loadedProfile
            self.plans = loadedPlans.map { plan in
                var copy = plan
                copy.isCurrent = copy.normalizedCode == currentCode
                return copy
            }
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func startCheckout(for plan: DesktopBillingPlan) async {
        if plan.isCurrent, let manageURL = summary?.manageURL {
            NSWorkspace.shared.open(manageURL)
            return
        }
        isLaunchingCheckout = true
        error = ""
        defer { isLaunchingCheckout = false }
        do {
            let checkout = try await appState.backend.createBillingCheckout(planCode: plan.code)
            guard let url = checkout.launchURL ?? checkout.paymentPageURL else {
                throw ElyanBackendError.malformedResponse("Ödeme bağlantısı alınamadı.")
            }
            NSWorkspace.shared.open(url)
        } catch {
            let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            if message.contains("billing_profile_incomplete") {
                self.error = "Fatura profili eksik. Önce aşağıdaki bilgileri tamamla."
                await refreshBillingProfile()
            } else {
                self.error = message
            }
        }
    }

    private func refreshBillingProfile() async {
        do {
            self.billingProfile = try await appState.backend.fetchBillingProfile()
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func saveBillingProfile() async {
        isSavingProfile = true
        error = ""
        defer { isSavingProfile = false }
        do {
            self.billingProfile = try await appState.backend.saveBillingProfile(billingProfile)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

fileprivate struct DesktopBillingPlan: Identifiable {
    let code: String
    let name: String
    let priceLabel: String
    let summary: String
    let highlights: [String]
    let primaryActionLabel: String
    let appleProductId: String?
    let googleProductId: String?
    var isCurrent: Bool = false

    var id: String { normalizedCode }
    var normalizedCode: String { code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
}

fileprivate struct DesktopBillingSummary {
    let planCode: String
    let planLabel: String
    let statusLabel: String?
    let tokensUsed: Int
    let tokensRemaining: Int
    let tasksUsed: Int
    let tasksRemaining: Int
    let desktopLimit: Int
    let desktopCount: Int
    let subscriptionSource: String?
    let manageSubscriptionHint: String?

    var manageURL: URL? {
        switch subscriptionSource?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "apple_store", "apple":
            return DesktopAppConfig.appleManageSubscriptionsURL
        case "google_play", "google":
            return DesktopAppConfig.googleManageSubscriptionsURL
        default:
            return nil
        }
    }
}

fileprivate struct DesktopBillingCheckout {
    let launchURL: URL?
    let paymentPageURL: URL?
}

fileprivate struct DesktopBillingProfile {
    var fullName: String
    var email: String
    var phone: String
    var identityNumber: String
    var addressLine1: String
    var city: String
    var country: String
    var zipCode: String
    var missingFields: [String]

    static let empty = DesktopBillingProfile(
        fullName: "",
        email: "",
        phone: "",
        identityNumber: "",
        addressLine1: "",
        city: "",
        country: "",
        zipCode: "",
        missingFields: []
    )

    var isComplete: Bool { missingFields.isEmpty && canSubmit }
    var canSubmit: Bool {
        [fullName, email, phone, identityNumber, addressLine1, city, country, zipCode]
            .allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

private struct CurrentPlanButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.secondary.opacity(configuration.isPressed ? 0.18 : 0.12))
            .foregroundStyle(.primary)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

private struct UpgradePlanButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.accentColor.opacity(configuration.isPressed ? 0.82 : 1.0))
            .foregroundStyle(.white)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

extension ElyanBackend {
    fileprivate func fetchBillingProfile() async throws -> DesktopBillingProfile {
        let raw = try await internalGetJSON(path: "/v1/billing/profile", requireAuth: true)
        let payload = Self.unwrap(raw)
        let profileState = (payload["profile"] as? [String: Any]) ?? payload
        let profile = (profileState["profile"] as? [String: Any]) ?? profileState
        let missingFields = Self.readStringList(profileState["missingFields"])
        return DesktopBillingProfile(
            fullName: profile["fullName"] as? String ?? "",
            email: profile["email"] as? String ?? "",
            phone: profile["phone"] as? String ?? "",
            identityNumber: profile["identityNumber"] as? String ?? "",
            addressLine1: profile["addressLine1"] as? String ?? "",
            city: profile["city"] as? String ?? "",
            country: profile["country"] as? String ?? "",
            zipCode: profile["zipCode"] as? String ?? "",
            missingFields: missingFields
        )
    }

    fileprivate func saveBillingProfile(_ profile: DesktopBillingProfile) async throws -> DesktopBillingProfile {
        let raw = try await putJSON(
            path: "/v1/billing/profile",
            body: [
                "fullName": profile.fullName,
                "email": profile.email,
                "phone": profile.phone,
                "identityNumber": profile.identityNumber,
                "addressLine1": profile.addressLine1,
                "city": profile.city,
                "country": profile.country,
                "zipCode": profile.zipCode,
            ],
            requireAuth: true
        )
        let payload = Self.unwrap(raw)
        let profileState = (payload["profile"] as? [String: Any]) ?? payload
        let nested = (profileState["profile"] as? [String: Any]) ?? profileState
        return DesktopBillingProfile(
            fullName: nested["fullName"] as? String ?? "",
            email: nested["email"] as? String ?? "",
            phone: nested["phone"] as? String ?? "",
            identityNumber: nested["identityNumber"] as? String ?? "",
            addressLine1: nested["addressLine1"] as? String ?? "",
            city: nested["city"] as? String ?? "",
            country: nested["country"] as? String ?? "",
            zipCode: nested["zipCode"] as? String ?? "",
            missingFields: Self.readStringList(profileState["missingFields"])
        )
    }

    fileprivate func fetchBillingPlans() async throws -> [DesktopBillingPlan] {
        let raw = try await internalGetJSON(path: "/v1/billing/plans", requireAuth: false)
        let payload = Self.unwrap(raw)
        let items = (payload["plans"] as? [[String: Any]]) ?? []
        return items.map { item in
            let providerProducts = item["providerProducts"] as? [String: Any] ?? [:]
            let apple = providerProducts["apple"] as? [String: Any] ?? [:]
            let google = providerProducts["google"] as? [String: Any] ?? [:]
            let monthlyPrice = item["monthlyPrice"] as? Double
            let label = (item["label"] as? String) ?? (item["name"] as? String) ?? ""
            let fallbackPriceLabel: String = {
                guard let monthlyPrice else { return "" }
                return String(format: "$%.2f/ay", monthlyPrice)
            }()
            return DesktopBillingPlan(
                code: item["code"] as? String ?? "free",
                name: label,
                priceLabel: (item["priceLabel"] as? String) ?? fallbackPriceLabel,
                summary: item["summary"] as? String ?? "",
                highlights: Self.readStringList(item["highlights"]) + Self.readStringList(item["features"]),
                primaryActionLabel: item["primaryActionLabel"] as? String ?? "Seç",
                appleProductId: apple["productId"] as? String,
                googleProductId: google["productId"] as? String
            )
        }
    }

    fileprivate func fetchBillingSummary() async throws -> DesktopBillingSummary {
        let raw = try await internalGetJSON(path: "/v1/billing/summary", requireAuth: true)
        let payload = Self.unwrap(raw)
        let billing = (payload["billing"] as? [String: Any]) ?? payload
        let subscription = billing["subscription"] as? [String: Any] ?? [:]
        let usage = billing["usage"] as? [String: Any] ?? [:]
        let entitlements = billing["entitlements"] as? [String: Any] ?? [:]
        let plan = billing["plan"] as? [String: Any] ?? [:]

        return DesktopBillingSummary(
            planCode: ((subscription["planCode"] as? String) ?? (plan["code"] as? String) ?? "free").lowercased(),
            planLabel: (billing["plan"] as? [String: Any]).flatMap { $0["label"] as? String }
                ?? (subscription["planCode"] as? String)?.capitalized
                ?? "Free",
            statusLabel: subscription["status"] as? String,
            tokensUsed: Self.readNestedInt(usage, keys: ["tokensUsed", "tokens", "used"]),
            tokensRemaining: Self.readNestedInt(usage, keys: ["tokensRemaining", "tokens", "remaining"]),
            tasksUsed: Self.readNestedInt(usage, keys: ["tasksUsed"]),
            tasksRemaining: Self.readNestedInt(usage, keys: ["tasksRemaining"]),
            desktopLimit: Self.readNestedInt(entitlements, keys: ["desktopLimit"]),
            desktopCount: Self.readNestedInt(billing, keys: ["desktopCount"]),
            subscriptionSource: subscription["subscriptionSource"] as? String ?? usage["subscriptionSource"] as? String,
            manageSubscriptionHint: subscription["manageSubscriptionHint"] as? String ?? usage["manageSubscriptionHint"] as? String
        )
    }

    fileprivate func createBillingCheckout(planCode: String) async throws -> DesktopBillingCheckout {
        let raw = try await postJSON(
            path: "/v1/billing/checkout/init",
            body: ["planCode": planCode.lowercased()],
            requireAuth: true
        )
        let payload = Self.unwrap(raw)
        let checkout = (payload["checkout"] as? [String: Any]) ?? payload
        let launchURL = (checkout["launchUrl"] as? String).flatMap(URL.init(string:))
        let paymentPageURL = (checkout["paymentPageUrl"] as? String).flatMap(URL.init(string:))
        return DesktopBillingCheckout(launchURL: launchURL, paymentPageURL: paymentPageURL)
    }

    fileprivate static func readNestedInt(_ value: [String: Any], keys: [String]) -> Int {
        if keys.count == 1 {
            return Self.readInt(value[keys[0]])
        }
        if let nested = value[keys[0]] as? [String: Any] {
            return readNestedInt(nested, keys: Array(keys.dropFirst()))
        }
        return 0
    }

    fileprivate static func readInt(_ value: Any?) -> Int {
        if let number = value as? Int { return number }
        if let number = value as? Double { return Int(number) }
        if let number = value as? NSNumber { return number.intValue }
        if let text = value as? String, let number = Int(text) { return number }
        return 0
    }

    fileprivate static func readStringList(_ value: Any?) -> [String] {
        guard let items = value as? [Any] else { return [] }
        return items.compactMap { item in
            let text = String(describing: item).trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? nil : text
        }
    }
}
