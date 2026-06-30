#!/usr/bin/env ruby
require 'fileutils'
require 'json'

src_dir = '/Users/emrekoca/Desktop/elyan png'
assets_dir = 'apps/macos/ElyanMac/Assets.xcassets'

Dir.glob("#{src_dir}/*.{png,webp,jpg,jpeg}").each_with_index do |file, index|
  ext = File.extname(file)
  name = "Bg_#{index + 1}"
  imageset_dir = File.join(assets_dir, "#{name}.imageset")
  
  FileUtils.mkdir_p(imageset_dir)
  FileUtils.cp(file, File.join(imageset_dir, "image#{ext}"))
  
  contents = {
    "images" => [
      {
        "filename" => "image#{ext}",
        "idiom" => "universal"
      }
    ],
    "info" => {
      "author" => "xcode",
      "version" => 1
    }
  }
  
  File.write(File.join(imageset_dir, 'Contents.json'), JSON.pretty_generate(contents))
  puts "Imported #{file} as #{name}"
end
