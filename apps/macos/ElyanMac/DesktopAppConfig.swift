import Foundation

enum DesktopAppConfig {
    // macOS-specific OAuth client (Google Cloud Console → OAuth 2.0 Client IDs
    // → iOS type, Bundle ID: com.elyan.mac). Distinct from the iOS/mobile
    // client used by elyan-mobile; both audiences are whitelisted in the
    // backend's GOOGLE_CLIENT_ID env so a single deployment serves both apps.
    static let googleClientID = "762420924659-9g27gaqn3f05liqrcnakj8s5k7v0d1o9.apps.googleusercontent.com"
    static let googleServerClientID = "762420924659-heq7v2qm19kqt9tj8tt14fef9u7s4dgh.apps.googleusercontent.com"
    static let googleReversedClientID = "com.googleusercontent.apps.762420924659-9g27gaqn3f05liqrcnakj8s5k7v0d1o9"
    static let appScheme = "elyan"

    static let appleManageSubscriptionsURL = URL(string: "https://apps.apple.com/account/subscriptions")
    static let googleManageSubscriptionsURL = URL(string: "https://play.google.com/store/account/subscriptions")
}
