# NASA SPHEREx 真實資料最小驗證

此報告由 verify_spherex.py 的實際執行產生。

- UTC：2026-11-14T09:55:22.303957+00:00
- 狀態：success
- 查詢：RA=127.69444, Dec=-39.1776, radius=0.01 deg；DR1 無結果才查 QR3。
- Cutout：3arcmin 完整邊長；不下載完整影像。
- 總執行秒數：18.603
- 程序最高 RSS bytes：74518528
- FITS bytes：3965760

## 執行紀錄

```json
{
  "started_utc": "2026-11-14T09:55:22.303957+00:00",
  "status": "success",
  "python": "3.11.1 (tags/v3.11.1:a7a450f, Dec  6 2022, 19:58:39) [MSC v.1934 64 bit (AMD64)]",
  "platform": "Windows-10-10.0.26200-SP0",
  "events": [
    {
      "url": "https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=CIRCLE+127.69444+-39.1776+0.01&MAXREC=50",
      "destination": "D:\\repo\\nasa\\research\\outputs\\spherex_dr1.xml",
      "bytes": 132034,
      "status": 200,
      "content_type": "application/x-votable+xml",
      "elapsed_seconds": 1.5361583999765571
    },
    {
      "url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W18_1B/l2b-v27-2026-196/1/level2_2025W18_1B_0162_1D1_spx_l2b-v27-2026-196.fits?center=127.69444%2C-39.1776deg&size=3arcmin",
      "destination": "D:\\repo\\nasa\\research\\outputs\\cutout.fits",
      "bytes": 0,
      "error": "<HTTPError 503: 'Service Unavailable'>",
      "elapsed_seconds": 1.007085499993991
    },
    {
      "url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W18_1B/l2b-v27-2026-196/4/level2_2025W18_1B_0162_1D4_spx_l2b-v27-2026-196.fits?center=127.69444%2C-39.1776deg&size=3arcmin",
      "destination": "D:\\repo\\nasa\\research\\outputs\\cutout.fits",
      "bytes": 0,
      "error": "<HTTPError 503: 'Service Unavailable'>",
      "elapsed_seconds": 0.5051393000176176
    },
    {
      "url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W18_1B/l2b-v27-2026-196/1/level2_2025W18_1B_0162_2D1_spx_l2b-v27-2026-196.fits?center=127.69444%2C-39.1776deg&size=3arcmin",
      "destination": "D:\\repo\\nasa\\research\\outputs\\cutout.fits",
      "bytes": 0,
      "error": "<HTTPError 503: 'Service Unavailable'>",
      "elapsed_seconds": 0.486762299988186
    },
    {
      "url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W18_1B/l2b-v27-2026-196/4/level2_2025W18_1B_0162_2D4_spx_l2b-v27-2026-196.fits?center=127.69444%2C-39.1776deg&size=3arcmin",
      "destination": "D:\\repo\\nasa\\research\\outputs\\cutout.fits",
      "bytes": 0,
      "error": "<HTTPError 503: 'Service Unavailable'>",
      "elapsed_seconds": 0.48051660001510754
    },
    {
      "url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/2025W18_1B/l2b-v27-2026-196/1/level2_2025W18_1B_0162_3D1_spx_l2b-v27-2026-196.fits?center=127.69444%2C-39.1776deg&size=3arcmin",
      "destination": "D:\\repo\\nasa\\research\\outputs\\cutout.fits",
      "bytes": 3965760,
      "status": 200,
      "content_type": "application/fits",
      "elapsed_seconds": 8.430719700001646
    }
  ],
  "errors": [
    {
      "candidate": 0,
      "error": "<HTTPError 503: 'Service Unavailable'>"
    },
    {
      "candidate": 1,
      "error": "<HTTPError 503: 'Service Unavailable'>"
    },
    {
      "candidate": 2,
      "error": "<HTTPError 503: 'Service Unavailable'>"
    },
    {
      "candidate": 3,
      "error": "<HTTPError 503: 'Service Unavailable'>"
    }
  ],
  "versions": {
    "astropy": "6.1.7",
    "numpy": "2.0.2",
    "Pillow": "11.3.0",
    "psutil": "7.2.2"
  },
  "query_status": {
    "spherex_dr1": [
      {
        "value": "OVERFLOW",
        "content": null
      }
    ]
  },
  "columns": {
    "spherex_dr1": [
      {
        "name": "s_ra",
        "unit": "deg",
        "description": "Central Spatial Position in ICRS Right ascension"
      },
      {
        "name": "s_dec",
        "unit": "deg",
        "description": "Central Spatial Position in ICRS Declination"
      },
      {
        "name": "facility_name",
        "unit": "None",
        "description": "Name of telescope used to acquire observation"
      },
      {
        "name": "instrument_name",
        "unit": "None",
        "description": "Name of instrument used to acquire observation"
      },
      {
        "name": "dataproduct_subtype",
        "unit": "None",
        "description": "Product type (e.g. science, calibration, auxiliary, preview, info)"
      },
      {
        "name": "calib_level",
        "unit": "None",
        "description": "Calibration level of the observation: in {0, 1, 2, 3, 4}"
      },
      {
        "name": "dataproduct_type",
        "unit": "None",
        "description": "Data product (file content) primary type"
      },
      {
        "name": "energy_bandpassname",
        "unit": "None",
        "description": "Collection-specific name for energy band (e.g. filter name)"
      },
      {
        "name": "energy_emband",
        "unit": "None",
        "description": "Generic name for energy band (Radio,Millimeter,Infrared,Optical,...)"
      },
      {
        "name": "obs_id",
        "unit": "None",
        "description": "Internal ID given by the ObsTAP service"
      },
      {
        "name": "s_resolution",
        "unit": "arcsec",
        "description": "Spatial resolution (FWHM)"
      },
      {
        "name": "em_min",
        "unit": "m",
        "description": "Lower bound on energy axis (barycentric wavelength)"
      },
      {
        "name": "em_max",
        "unit": "m",
        "description": "Upper bound on energy axis (barycentric wavelength)"
      },
      {
        "name": "em_res_power",
        "unit": "None",
        "description": "Spectral resolving power (R)"
      },
      {
        "name": "proposal_title",
        "unit": "None",
        "description": "Proposal title"
      },
      {
        "name": "access_url",
        "unit": "None",
        "description": "URI for the physical artifact"
      },
      {
        "name": "access_format",
        "unit": "None",
        "description": "Content-Type of the representation at uri"
      },
      {
        "name": "access_estsize",
        "unit": "kbyte",
        "description": "Estimated size of the download at uri"
      },
      {
        "name": "t_exptime",
        "unit": "s",
        "description": "Exposure time per pixel"
      },
      {
        "name": "s_region",
        "unit": "deg",
        "description": "AstroCoordArea Region covered in STC"
      },
      {
        "name": "obs_collection",
        "unit": "None",
        "description": "Data collection this observation belongs to"
      },
      {
        "name": "obs_intent",
        "unit": "None",
        "description": "Intended purpose of data (one of: science, calibration)"
      },
      {
        "name": "algorithm_name",
        "unit": "None",
        "description": "Algorithm that defines the observation"
      },
      {
        "name": "facility_keywords",
        "unit": "None",
        "description": "Telescope keywords formatted as a JSON string"
      },
      {
        "name": "instrument_keywords",
        "unit": "None",
        "description": "Instrument keywords formatted as a JSON string"
      },
      {
        "name": "environment_photometric",
        "unit": "None",
        "description": "Conditions were photometric (0=false, 1=true)"
      },
      {
        "name": "proposal_id",
        "unit": "None",
        "description": "Collection-specific unique proposal identifier"
      },
      {
        "name": "proposal_pi",
        "unit": "None",
        "description": "Proposal principal investigator"
      },
      {
        "name": "proposal_project",
        "unit": "None",
        "description": "Project that created/acquired the observation"
      },
      {
        "name": "target_name",
        "unit": "None",
        "description": "Name of intended target"
      },
      {
        "name": "target_type",
        "unit": "None",
        "description": "Classification of intended target ('object' or 'field')"
      },
      {
        "name": "target_standard",
        "unit": "None",
        "description": "Intended target is a standard (0=false, 1=true)"
      },
      {
        "name": "target_moving",
        "unit": "None",
        "description": "Intended target is moving (0=false, 1=true)"
      },
      {
        "name": "target_keywords",
        "unit": "None",
        "description": "Target keywords formatted as a JSON string"
      },
      {
        "name": "obs_release_date",
        "unit": "None",
        "description": "Timestamp of date the data becomes publicly available"
      },
      {
        "name": "s_xel1",
        "unit": "None",
        "description": "Dimensions (number of pixels) along first spatial axis"
      },
      {
        "name": "s_xel2",
        "unit": "None",
        "description": "Dimensions (number of pixels) along second spatial axis"
      },
      {
        "name": "s_pixel_scale",
        "unit": "arcsec",
        "description": "Sample (pixel) size on spatial axes"
      },
      {
        "name": "position_timedependent",
        "unit": "None",
        "description": "Position is time-dependent (0=false, 1=true)"
      },
      {
        "name": "t_min",
        "unit": "d",
        "description": "Lower bound on time axis (Modified Julian Day)"
      },
      {
        "name": "t_max",
        "unit": "d",
        "description": "Upper bound on time axis (Modified Julian Day)"
      },
      {
        "name": "t_resolution",
        "unit": "s",
        "description": "Resolution on the time axis"
      },
      {
        "name": "t_xel",
        "unit": "None",
        "description": "Dimensions (number of pixels) along the time axis"
      },
      {
        "name": "obs_publisher_did",
        "unit": "None",
        "description": "IVOA Dataset ID given by the publisher"
      },
      {
        "name": "s_fov",
        "unit": "deg",
        "description": "Estimated size of the covered region as the diameter of a containing circle"
      },
      {
        "name": "em_xel",
        "unit": "None",
        "description": "Dimensions (number of pixels) along the energy axis"
      },
      {
        "name": "pol_states",
        "unit": "None",
        "description": "List of polarization states present in the data file"
      },
      {
        "name": "pol_xel",
        "unit": "None",
        "description": "Dimensions (number of pixels) along the polarization axis"
      },
      {
        "name": "cloud_access",
        "unit": "None",
        "description": "URI for the enclouded artifact"
      },
      {
        "name": "o_ucd",
        "unit": "None",
        "description": "UCD describing the observable axis (pixel values)"
      },
      {
        "name": "upload_row_id",
        "unit": "None",
        "description": null
      }
    ]
  },
  "image_count_returned": 50,
  "fits_bytes": 3965760,
  "selected_obs_id": "2025W18_1B_0162_3",
  "detector": 1,
  "image_shape": [
    29,
    29
  ],
  "hdu_summary": [
    {
      "name": "PRIMARY",
      "type": "PrimaryHDU",
      "axes": [],
      "bitpix": 8
    },
    {
      "name": "IMAGE",
      "type": "ImageHDU",
      "axes": [
        29,
        29
      ],
      "bitpix": -32
    },
    {
      "name": "FLAGS",
      "type": "ImageHDU",
      "axes": [
        29,
        29
      ],
      "bitpix": 32
    },
    {
      "name": "VARIANCE",
      "type": "ImageHDU",
      "axes": [
        29,
        29
      ],
      "bitpix": -32
    },
    {
      "name": "ZODI",
      "type": "ImageHDU",
      "axes": [
        29,
        29
      ],
      "bitpix": -32
    },
    {
      "name": "EPSF",
      "type": "BinTableHDU",
      "axes": [
        8752,
        441
      ],
      "bitpix": 8
    },
    {
      "name": "WCS-WAVE",
      "type": "BinTableHDU",
      "axes": [
        720,
        1
      ],
      "bitpix": 8
    }
  ],
  "peak_rss_bytes": 74518528,
  "memory_method": "20 ms RSS polling plus Windows peak_wset when available; process only",
  "elapsed_seconds": 18.60312569999951
}
```

## 檢查方式

查看 outputs/images.csv、metadata.json、run.json 以及保存的 SIA VOTable。
成功時開啟 outputs/black-background.png 和 outputs/white-background.png。
outputs/ 與 FITS 已由 research/.gitignore 排除；不應提交大型資料。
