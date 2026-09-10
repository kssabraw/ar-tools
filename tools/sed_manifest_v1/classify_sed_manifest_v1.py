#!/usr/bin/env python3
import csv, hashlib, json, math, os, pathlib, urllib.request
from collections import Counter, defaultdict

import geopandas as gpd
from pyproj import Geod
from shapely.geometry import Point, LineString

VINTAGE = "2025"
CLASSIFIER_VERSION = "SED_GEO_ELIGIBILITY_CENSUS_2025_V1"
AUTO_EXCLUDE = {"H2030","H2040","H2041","H2051","H2053","H3010"}
BASE = "https://www2.census.gov/geo/tiger/TIGER2025"
STATE_URL = BASE + "/STATE/tl_2025_us_state.zip"
COUNTY_URL = BASE + "/COUNTY/tl_2025_us_county.zip"
INTL_URL = BASE + "/INTERNATIONALBOUNDARY/tl_2025_us_internationalboundary.zip"
WATER_URL = BASE + "/AREAWATER/tl_2025_{geoid}_areawater.zip"
ANCHORS = [('MKT001', 'Los Angeles', 'CA', 34.05378, -118.2429),
 ('MKT002', 'San Diego', 'CA', 32.71698, -117.16281),
 ('MKT003', 'San Francisco', 'CA', 37.779255, -122.419182),
 ('MKT004', 'Sacramento', 'CA', 38.582084, -121.493439),
 ('MKT005', 'Fresno', 'CA', 36.73969, -119.78451),
 ('MKT006', 'Bakersfield', 'CA', 35.37278, -119.01944),
 ('MKT007', 'Portland', 'OR', 45.515014, -122.67911),
 ('MKT008', 'Vancouver', 'WA', 45.625655, -122.6754998),
 ('MKT009', 'Seattle', 'WA', 47.603878, -122.330001),
 ('MKT010', 'Spokane', 'WA', 47.65981, -117.42253),
 ('MKT011', 'Phoenix', 'AZ', 33.44879, -112.0771),
 ('MKT012', 'Tucson', 'AZ', 32.22257, -110.97476),
 ('MKT013', 'Las Vegas', 'NV', 36.16739, -115.1485),
 ('MKT014', 'Reno', 'NV', 39.52616, -119.81265),
 ('MKT015', 'Salt Lake City', 'UT', 40.759583, -111.886806),
 ('MKT016', 'Denver', 'CO', 39.73944, -104.98889),
 ('MKT017', 'Colorado Springs', 'CO', 38.8356083, -104.8209972),
 ('MKT018', 'Boise', 'ID', 43.61512, -116.20138),
 ('MKT019', 'Albuquerque', 'NM', 35.08768, -106.65167),
 ('MKT020', 'Fort Collins', 'CO', 40.58985, -105.08191),
 ('MKT021', 'Chicago', 'IL', 41.88385, -87.63195),
 ('MKT022', 'Minneapolis', 'MN', 44.9773, -93.2654),
 ('MKT023', 'Milwaukee', 'WI', 43.04171, -87.90979),
 ('MKT024', 'Detroit', 'MI', 42.3295, -83.04426),
 ('MKT025', 'Columbus', 'OH', 39.96265, -83.00337),
 ('MKT026', 'Cincinnati', 'OH', 39.10423, -84.51939),
 ('MKT027', 'Indianapolis', 'IN', 39.76797, -86.15354),
 ('MKT028', 'St. Louis', 'MO', 38.626812, -90.199406),
 ('MKT029', 'Kansas City', 'MO', 39.10062, -94.57792),
 ('MKT030', 'Grand Rapids', 'MI', 42.96927, -85.67151),
 ('MKT031', 'Dallas', 'TX', 32.77627, -96.79694),
 ('MKT032', 'Houston', 'TX', 29.76018, -95.36937),
 ('MKT033', 'Austin', 'TX', 30.26479, -97.7472),
 ('MKT034', 'San Antonio', 'TX', 29.4245868, -98.4951446),
 ('MKT035', 'Nashville', 'TN', 36.16722, -86.77861),
 ('MKT036', 'Memphis', 'TN', 35.14842, -90.05092),
 ('MKT037', 'Atlanta', 'GA', 33.74862, -84.39059),
 ('MKT038', 'Charlotte', 'NC', 35.2215526, -80.8393081),
 ('MKT039', 'Raleigh', 'NC', 35.778799, -78.64293),
 ('MKT040', 'Birmingham', 'AL', 33.51955, -86.81082),
 ('MKT041', 'Miami', 'FL', 25.7276845, -80.2337652),
 ('MKT042', 'Tampa', 'FL', 27.94766, -82.45724),
 ('MKT043', 'Orlando', 'FL', 28.5376214, -81.3796806),
 ('MKT044', 'Jacksonville', 'FL', 30.329698, -81.658821),
 ('MKT045', 'Richmond', 'VA', 37.54099, -77.43296),
 ('MKT046', 'Washington', 'DC', 38.89501, -77.03134),
 ('MKT047', 'Baltimore', 'MD', 39.29088, -76.61069),
 ('MKT048', 'Philadelphia', 'PA', 39.95233, -75.16351),
 ('MKT049', 'New York City', 'NY', 40.71274, -74.00601),
 ('MKT050', 'Boston', 'MA', 42.36043, -71.05796)]
GEOD = Geod(ellps="WGS84")
MILES_TO_M = 1609.344

MAPORG = [
    ("C", 0, None), ("N1",1,0), ("E1",1,90), ("S1",1,180), ("W1",1,270),
    ("N3",3,0), ("E3",3,90), ("S3",3,180), ("W3",3,270),
    ("N5",5,0), ("E5",5,90), ("S5",5,180), ("W5",5,270)
]
AIO = [
    ("C",0,None), ("N2P5",2.5,0), ("E2P5",2.5,90), ("S2P5",2.5,180), ("W2P5",2.5,270),
    ("N5",5,0), ("E5",5,90), ("S5",5,180), ("W5",5,270)
]

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def dl(url, path):
    path=pathlib.Path(path)
    if not path.exists():
        print("DOWNLOAD", url, flush=True)
        urllib.request.urlretrieve(url, path)
    return path

def build_coords():
    out=[]
    for market_id,city,state,lat0,lon0 in ANCHORS:
        for surface, geom, spec in (("maps_organic","MAPORG13_V1",MAPORG),("aio","AIO9_V1",AIO)):
            for pid,dist,bearing in spec:
                if dist==0:
                    lat,lon=lat0,lon0
                else:
                    lon,lat,_=GEOD.fwd(lon0,lat0,bearing,dist*MILES_TO_M)
                    lat=round(lat,7); lon=round(lon,7)
                out.append(dict(
                    coordinate_id=f"{market_id}_{'MAPORG' if surface=='maps_organic' else 'AIO'}_{pid}",
                    market_id=market_id, city=city, state=state, surface_group=surface,
                    geometry_id=geom, point_id=pid, distance_miles=dist,
                    latitude=lat, longitude=lon, center_latitude=lat0, center_longitude=lon0
                ))
    return out

def geodesic_line(row, steps=64):
    lon0,lat0=row["center_longitude"],row["center_latitude"]
    lon1,lat1=row["longitude"],row["latitude"]
    if row["point_id"]=="C":
        return LineString([(lon0,lat0),(lon0,lat0)])
    mids=GEOD.npts(lon0,lat0,lon1,lat1,steps-1)
    return LineString([(lon0,lat0),*mids,(lon1,lat1)])

def main():
    work=pathlib.Path("sed_manifest_work")
    work.mkdir(exist_ok=True)
    sources=work/"sources"; sources.mkdir(exist_ok=True)
    outdir=pathlib.Path("sed_manifest_output"); outdir.mkdir(exist_ok=True)

    state_zip=dl(STATE_URL,sources/"tl_2025_us_state.zip")
    county_zip=dl(COUNTY_URL,sources/"tl_2025_us_county.zip")
    intl_zip=dl(INTL_URL,sources/"tl_2025_us_internationalboundary.zip")

    coords=build_coords()
    assert len(coords)==1100
    points=gpd.GeoDataFrame(coords, geometry=[Point(r["longitude"],r["latitude"]) for r in coords], crs="EPSG:4326")
    lines=gpd.GeoDataFrame(
        {"coordinate_id":[r["coordinate_id"] for r in coords]},
        geometry=[geodesic_line(r) for r in coords], crs="EPSG:4326"
    )

    states=gpd.read_file("zip://"+str(state_zip)).to_crs("EPSG:4326")
    counties=gpd.read_file("zip://"+str(county_zip)).to_crs("EPSG:4326")
    intl=gpd.read_file("zip://"+str(intl_zip)).to_crs("EPSG:4326")

    centers=points[points.point_id=="C"].copy()
    center_join=gpd.sjoin(centers[["coordinate_id","geometry"]],states[["geometry"]],how="left",predicate="intersects")
    bad_centers=set(center_join[center_join["index_right"].isna()]["coordinate_id"])
    if bad_centers:
        raise SystemExit("CENTER COUNTRY CONFIGURATION FAILURE: "+",".join(sorted(bad_centers)))

    line5070=lines.to_crs("EPSG:5070")
    intl5070=intl.to_crs("EPSG:5070")
    crossings=gpd.sjoin(line5070, intl5070[["geometry"]],how="left",predicate="intersects")
    cross_ids=set(crossings[~crossings["index_right"].isna()]["coordinate_id"])
    cross_ids={x for x in cross_ids if not x.endswith("_C")}

    in_points=points[~points.coordinate_id.isin(cross_ids)].copy()
    county_join=gpd.sjoin(in_points[["coordinate_id","geometry"]],counties[["GEOID","NAME","geometry"]],how="left",predicate="intersects")
    missing_county=set(county_join[county_join["GEOID"].isna()]["coordinate_id"])
    if missing_county:
        mpts=in_points[in_points.coordinate_id.isin(missing_county)].to_crs("EPSG:5070")
        mcts=counties[["GEOID","NAME","geometry"]].to_crs("EPSG:5070")
        nearest=gpd.sjoin_nearest(mpts,mcts,how="left",max_distance=25000,distance_col="route_distance_m")
        add=nearest[["coordinate_id","GEOID","NAME"]].copy()
        add["geometry"]=None
        county_join = county_join[~county_join.coordinate_id.isin(missing_county)]
        import pandas as pd
        county_join = gpd.GeoDataFrame(pd.concat([county_join[["coordinate_id","GEOID","NAME","geometry"]],add],ignore_index=True),geometry="geometry",crs="EPSG:4326")
    still_missing=set(county_join[county_join["GEOID"].isna()]["coordinate_id"])
    if still_missing:
        raise SystemExit("COUNTY ROUTING FAILURE: "+",".join(sorted(still_missing)))

    route=defaultdict(set)
    for _,r in county_join.iterrows():
        if r["GEOID"]==r["GEOID"]: route[r["coordinate_id"]].add(str(r["GEOID"]))
    geoids=sorted({g for s in route.values() for g in s})
    print("COUNTIES",len(geoids),geoids,flush=True)

    water_frames=[]
    water_sources=[]
    for geoid in geoids:
        fn=f"tl_2025_{geoid}_areawater.zip"
        p=dl(WATER_URL.format(geoid=geoid),sources/fn)
        water_sources.append((fn,sha256(p)))
        g=gpd.read_file("zip://"+str(p)).to_crs("EPSG:4326")
        g["_source_file"]=fn
        water_frames.append(g)
    import pandas as pd
    water=gpd.GeoDataFrame(pd.concat(water_frames,ignore_index=True),crs="EPSG:4326")

    hcols=[c for c in ["MTFCC","FULLNAME","HYDROID","LINEARID","_source_file","geometry"] if c in water.columns]
    wjoin=gpd.sjoin(in_points[["coordinate_id","geometry"]],water[hcols],how="left",predicate="intersects")
    matches=defaultdict(list)
    for _,r in wjoin.iterrows():
        mt=r.get("MTFCC")
        if mt is None or (isinstance(mt,float) and math.isnan(mt)): continue
        matches[r["coordinate_id"]].append({
            "MTFCC":str(mt),
            "FULLNAME":None if "FULLNAME" not in r or r.get("FULLNAME") is None else str(r.get("FULLNAME")),
            "HYDROID":None if "HYDROID" not in r or r.get("HYDROID") is None else str(r.get("HYDROID")),
            "source_file":None if "_source_file" not in r else str(r.get("_source_file"))
        })

    results=[]; counts=Counter()
    for r in coords:
        cid=r["coordinate_id"]
        is_center=r["point_id"]=="C"
        if cid in cross_ids:
            status="configuration_failure" if is_center else "outside_country_exclusion"
            eligibility="BLOCKED_CONFIGURATION_FAILURE" if is_center else "STRUCTURAL_EXCLUSION"
            ms=[]
        else:
            ms=matches.get(cid,[])
            mtfccs=sorted({m["MTFCC"] for m in ms})
            auto=sorted(set(mtfccs)&AUTO_EXCLUDE)
            if auto:
                status="configuration_failure" if is_center else "structural_water_exclusion"
                eligibility="BLOCKED_CONFIGURATION_FAILURE" if is_center else "STRUCTURAL_EXCLUSION"
            elif ms:
                status="manual_review"; eligibility="BLOCKED_MANUAL_REVIEW"
            else:
                status="eligible_land"; eligibility="ELIGIBLE"
        counts[status]+=1
        mtfccs=sorted({m["MTFCC"] for m in ms})
        results.append({
            **{k:r[k] for k in ["coordinate_id","market_id","city","state","surface_group","geometry_id","point_id","distance_miles","latitude","longitude"]},
            "country_boundary_status":"outside_country_exclusion" if cid in cross_ids else "in_country",
            "water_eligibility_status":status if status not in ("outside_country_exclusion",) else "not_evaluated_outside_country",
            "collection_eligibility":eligibility,
            "matched_feature_count":len(ms),
            "matched_mtfccs":";".join(mtfccs),
            "matched_names":";".join(sorted({m["FULLNAME"] for m in ms if m["FULLNAME"] and m["FULLNAME"]!="nan"})),
            "matched_hydroids":";".join(sorted({m["HYDROID"] for m in ms if m["HYDROID"] and m["HYDROID"]!="nan"})),
            "matched_water_source_files":";".join(sorted({m["source_file"] for m in ms if m["source_file"] and m["source_file"]!="nan"})),
            "classifier_version":CLASSIFIER_VERSION
        })

    fields=list(results[0].keys())
    csv_path=outdir/"SED_Geo_Eligibility_Classification_v1_0.csv"
    with open(csv_path,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(results)

    source_manifest={
        "classifier_version":CLASSIFIER_VERSION,
        "boundary_source":{
            "role":"country_boundary_gate",
            "file":"tl_2025_us_internationalboundary.zip",
            "url":INTL_URL,
            "sha256":sha256(intl_zip),
            "method":"verified-U.S.-center to treatment-point geodesic ray intersects official international boundary"
        },
        "center_qa_source":{"file":"tl_2025_us_state.zip","url":STATE_URL,"sha256":sha256(state_zip)},
        "county_routing_source":{"file":"tl_2025_us_county.zip","url":COUNTY_URL,"sha256":sha256(county_zip)},
        "water_sources":[{"file":fn,"url":WATER_URL.format(geoid=fn.split("_")[2]),"sha256":h} for fn,h in water_sources],
        "auto_exclude_mtfcc":sorted(AUTO_EXCLUDE),
        "coordinate_method":"WGS84_GEODESIC_DIRECT; 7-decimal output",
        "coordinate_count":len(coords)
    }
    sm_path=outdir/"SED_Geo_Source_Manifest_v1_0.json"
    sm_path.write_text(json.dumps(source_manifest,indent=2),encoding="utf-8")

    report={
        "classifier_version":CLASSIFIER_VERSION,
        "coordinate_count":len(coords),
        "status_counts":dict(counts),
        "outside_country_coordinate_ids":sorted(cross_ids),
        "manual_review_coordinate_ids":sorted([x["coordinate_id"] for x in results if x["water_eligibility_status"]=="manual_review"]),
        "configuration_failure_coordinate_ids":sorted([x["coordinate_id"] for x in results if x["water_eligibility_status"]=="configuration_failure"]),
        "classification_csv_sha256":sha256(csv_path),
        "source_manifest_sha256":sha256(sm_path),
        "county_file_count":len(geoids)
    }
    rp=outdir/"SED_Geo_Eligibility_Report_v1_0.json"
    rp.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2),flush=True)

if __name__=="__main__":
    main()
