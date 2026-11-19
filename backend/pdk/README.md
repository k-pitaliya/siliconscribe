# Cell library for mapped area and timing

`sky130hd_tt.lib` is the SkyWater 130 nm high-density standard-cell library, typical corner
(25 C, 1.8 V), Apache-2.0. It is not committed (12 MB). Fetch it with:

```
cd backend/pdk
curl -fsSL -o sky130hd_tt.lib.gz https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/examples/sky130hd_tt.lib.gz
gunzip -kf sky130hd_tt.lib.gz
```

Without it the app reports mapped area and timing as "not available" (it never invents numbers).
