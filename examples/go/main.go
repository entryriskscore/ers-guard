// Reads the ers-guard sidecar (start it with: ers-guard serve). Go 1.18+.
package main

import ("encoding/json"; "fmt"; "net/http")

func main() {
	r, err := http.Get("http://127.0.0.1:8787/check?symbol=ETHUSDT&side=LONG&hold=60m")
	if err != nil { fmt.Println("sidecar not running:", err); return }
	defer r.Body.Close()
	var res struct{ Level string `json:"level"`; Score *float64 `json:"score"`; Reason string `json:"reason"` }
	json.NewDecoder(r.Body).Decode(&res)
	fmt.Println(res.Level, res.Reason)
}
