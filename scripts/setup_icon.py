import os
import shutil
import subprocess

source_img = "/Users/emrekoca/Desktop/elyan-icon.icon/Assets/logo 2.png"
if not os.path.exists(source_img):
    source_img = "/Users/emrekoca/Desktop/elyan-icon.icon/Assets/Adsız tasarım.png"

xcassets_dir = "apps/macos/ElyanMac/Assets.xcassets"
appiconset_dir = os.path.join(xcassets_dir, "AppIcon.appiconset")

os.makedirs(appiconset_dir, exist_ok=True)

# Generate Contents.json
contents_json = """{
  "images" : [
    {
      "idiom" : "mac",
      "size" : "1024x1024",
      "scale" : "1x",
      "filename" : "icon_1024x1024.png"
    }
  ],
  "info" : {
    "version" : 1,
    "author" : "xcode"
  }
}"""

with open(os.path.join(appiconset_dir, "Contents.json"), "w") as f:
    f.write(contents_json)

# Copy and resize image (macOS sips command)
dest_img = os.path.join(appiconset_dir, "icon_1024x1024.png")
shutil.copy(source_img, dest_img)
subprocess.run(["sips", "-z", "1024", "1024", dest_img])

# Update ruby script to include Assets.xcassets and set icon name
ruby_script_path = "scripts/generate_mac_proj.rb"
with open(ruby_script_path, "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    if "app_target.add_file_references([file_ref])" in line:
        pass # just keep it
    if "Dir.glob" in line:
        pass
    if "config.build_settings['GENERATE_INFOPLIST_FILE'] = 'YES'" in line:
        new_lines.append("    config.build_settings['ASSETCATALOG_COMPILER_APPICON_NAME'] = 'AppIcon'\n")

# Need to add Assets.xcassets to resources
resource_code = """
assets_ref = group.new_reference('Assets.xcassets')
app_target.add_resources([assets_ref])
"""
# Insert before config iteration
insert_idx = 0
for i, line in enumerate(new_lines):
    if "app_target.build_configurations.each do |config|" in line:
        insert_idx = i
        break

new_lines.insert(insert_idx, resource_code)

with open(ruby_script_path, "w") as f:
    f.writelines(new_lines)

print("Icon setup complete.")
