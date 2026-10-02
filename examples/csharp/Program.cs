// Reads the ers-guard sidecar (start it with: ers-guard serve). .NET 6+ top-level program.
using System.Net.Http.Json;

var http = new HttpClient();
var r = await http.GetFromJsonAsync<Check>("http://127.0.0.1:8787/check?symbol=ETHUSDT&side=LONG&hold=60m");
Console.WriteLine($"{r?.level} {r?.reason}");
if (r?.level == "HIGH") Console.WriteLine("Entry skipped by my own policy.");

record Check(string level, double? score, string reason);
