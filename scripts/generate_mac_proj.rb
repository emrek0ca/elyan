require 'xcodeproj'

project_path = 'apps/macos/ElyanMac/ElyanMac.xcodeproj'
project = Xcodeproj::Project.new(project_path)

app_target = project.new_target(:application, 'ElyanMac', :osx)

# Add source files
group = project.main_group.find_subpath(File.join('.'), true)
group.set_source_tree('SOURCE_ROOT')

Dir.glob('apps/macos/ElyanMac/*.swift').each do |file|
    file_ref = group.new_reference(File.basename(file))
    app_target.add_file_references([file_ref])
end

# Set settings

assets_ref = group.new_reference('Assets.xcassets')
app_target.add_resources([assets_ref])
app_target.build_configurations.each do |config|
    config.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = 'com.elyan.mac'
    config.build_settings['INFOPLIST_KEY_NSPrincipalClass'] = 'NSApplication'
    config.build_settings['PRODUCT_NAME'] = 'Elyan'
    config.build_settings['SWIFT_VERSION'] = '5.0'
    config.build_settings['MACOSX_DEPLOYMENT_TARGET'] = '14.0'
    config.build_settings['GENERATE_INFOPLIST_FILE'] = 'YES'
    config.build_settings['ASSETCATALOG_COMPILER_APPICON_NAME'] = 'AppIcon'
end

project.save
