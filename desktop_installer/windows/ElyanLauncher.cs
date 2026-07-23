using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

internal static class ElyanLauncher
{
    private static string QuoteArgument(string value)
    {
        if (value.Length > 0 && value.All(character => !char.IsWhiteSpace(character) && character != '"'))
        {
            return value;
        }

        var result = new StringBuilder("\"");
        var backslashes = 0;
        foreach (var character in value)
        {
            if (character == '\\')
            {
                backslashes += 1;
                continue;
            }
            if (character == '"')
            {
                result.Append('\\', backslashes * 2 + 1);
                result.Append('"');
                backslashes = 0;
                continue;
            }
            result.Append('\\', backslashes);
            backslashes = 0;
            result.Append(character);
        }
        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }

    private static int Main(string[] args)
    {
        try
        {
            var root = AppDomain.CurrentDomain.BaseDirectory;
            var payload = Path.Combine(root, "payload");
            var pythonRoot = Path.Combine(payload, "python");
            var python = Directory.Exists(pythonRoot)
                ? Directory.GetDirectories(pythonRoot, "cpython-*")
                    .Select(directory => Path.Combine(directory, "python.exe"))
                    .FirstOrDefault(File.Exists)
                : null;
            var bootstrap = Path.Combine(payload, "bootstrap.py");
            if (python == null || !File.Exists(bootstrap))
            {
                Console.Error.WriteLine("Elyan paketi eksik veya bozuk. Elyan'i yeniden indirin.");
                return 1;
            }

            var arguments = new List<string> { bootstrap, "--payload", payload };
            arguments.AddRange(args);
            var startInfo = new ProcessStartInfo
            {
                FileName = python,
                Arguments = string.Join(" ", arguments.Select(QuoteArgument)),
                UseShellExecute = false,
                WorkingDirectory = root,
            };
            using (var process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    Console.Error.WriteLine("Elyan baslatilamadi.");
                    return 1;
                }
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    Console.Error.WriteLine("Kurulum tamamlanamadi. Ayrintilar yukarida.");
                    Console.WriteLine("Pencereyi kapatmak icin Enter'a basin.");
                    Console.ReadLine();
                }
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Elyan baslatilamadi: " + error.Message);
            Console.WriteLine("Pencereyi kapatmak icin Enter'a basin.");
            Console.ReadLine();
            return 1;
        }
    }
}
