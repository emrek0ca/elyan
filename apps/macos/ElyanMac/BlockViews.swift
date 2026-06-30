import SwiftUI

struct BlockView: View {
    let blockType: String
    let content: String
    
    var body: some View {
        HStack {
            if blockType == "user" {
                Spacer()
                Text(content)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .foregroundColor(.white)
                    .background(Color.accentColor)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            } else if blockType == "text" {
                Text(content)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .foregroundColor(.primary)
                    .background(Material.thick)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                Spacer()
            } else if blockType == "status" {
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.small)
                    Text(content)
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Material.ultraThin)
                .clipShape(Capsule())
                Spacer()
            } else if blockType == "artifact" || blockType == "tool" || blockType == "action" {
                HStack(spacing: 12) {
                    Image(systemName: blockType == "artifact" ? "doc.richtext.fill" : "hammer.fill")
                        .foregroundColor(.accentColor)
                        .font(.system(size: 20))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(blockType.capitalized)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)
                        Text(content)
                            .font(.subheadline)
                            .fontWeight(.medium)
                            .foregroundColor(.primary)
                    }
                }
                .padding(12)
                .background(Material.regular)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(Color.primary.opacity(0.1), lineWidth: 1)
                )
                Spacer()
            } else if blockType == "error" {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.red)
                    Text(content.isEmpty ? "Bir hata oluştu." : content)
                        .font(.subheadline)
                        .foregroundColor(.red)
                }
                .padding(12)
                .background(Color.red.opacity(0.1))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Spacer()
            } else {
                Text(content)
                    .padding()
                    .background(Material.regular)
                    .cornerRadius(12)
                Spacer()
            }
        }
        .padding(.horizontal, 4)
    }
}
