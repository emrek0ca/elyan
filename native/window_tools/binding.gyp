{
  "targets": [
    {
      "target_name": "window_tools",
      "sources": [
        "src/window_tools.cc"
      ],
      "conditions": [
        [
          "OS=='mac'",
          {
            "sources": [
              "src/window_tools_mac.mm"
            ],
            "libraries": [
              "-framework AppKit",
              "-framework ApplicationServices"
            ]
          },
          {
            "sources": [
              "src/window_tools_stub.cc"
            ]
          }
        ]
      ],
      "include_dirs": [
        "<!@(node -p \"require('node-addon-api').include\")"
      ],
      "dependencies": [
        "<!(node -p \"require('node-addon-api').gyp\")"
      ],
      "defines": [
        "NAPI_DISABLE_CPP_EXCEPTIONS"
      ],
      "cflags_cc!": [
        "-fno-exceptions"
      ],
      "xcode_settings": {
        "GCC_ENABLE_CPP_EXCEPTIONS": "NO",
        "CLANG_ENABLE_OBJC_ARC": "YES",
        "CLANG_CXX_LIBRARY": "libc++",
        "MACOSX_DEPLOYMENT_TARGET": "11.0"
      },
      "msvs_settings": {
        "VCCLCompilerTool": {
          "ExceptionHandling": 0
        }
      }
    }
  ]
}
