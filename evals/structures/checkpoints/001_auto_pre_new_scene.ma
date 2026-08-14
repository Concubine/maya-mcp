//Maya ASCII 2027 scene
//Name: 001_auto_pre_new_scene.ma
//Last modified: Fri, Aug 14, 2026 11:42:42 PM
//Codeset: 1252
requires maya "2027";
requires "mtoa" "5.6.2";
requires -nodeType "UsdDefaultSettings" -dataType "pxrUsdStageData" "mayaUsdPlugin" "0.37.0";
currentUnit -l centimeter -a degree -t film;
fileInfo "application" "maya";
fileInfo "product" "Maya 2027";
fileInfo "version" "2027";
fileInfo "cutIdentifier" "202607171511-52c21617ee";
fileInfo "osv" "Windows 11 Pro v2009 (Build: 26200)";
fileInfo "UUID" "221F9FB9-432E-77BB-F9BE-65A9B48C064B";
fileInfo "exportedFrom" "D:/devel/maya-mcp/evals/structures/rotunda.ma";
createNode transform -s -n "persp";
	rename -uid "33045C13-4E16-66A1-8C5B-07A29CF79545";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 28 21 28 ;
	setAttr ".r" -type "double3" -27.938352729602379 44.999999999999972 -5.172681101354183e-14 ;
createNode camera -s -n "perspShape" -p "persp";
	rename -uid "BB22C342-4E26-B899-574B-17AB882639D4";
	setAttr -k off ".v" no;
	setAttr ".fl" 34.999999999999993;
	setAttr ".coi" 44.82186966202994;
	setAttr ".imn" -type "string" "persp";
	setAttr ".den" -type "string" "persp_depth";
	setAttr ".man" -type "string" "persp_mask";
	setAttr ".hc" -type "string" "viewSet -p %camera";
createNode transform -s -n "top";
	rename -uid "1AD571FC-4E4E-BAD4-281D-0C955F53E483";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 0 1000.1 0 ;
	setAttr ".r" -type "double3" -90 0 0 ;
createNode camera -s -n "topShape" -p "top";
	rename -uid "C22D2BFA-41A1-E91B-8B50-A486AE73F364";
	setAttr -k off ".v" no;
	setAttr ".rnd" no;
	setAttr ".coi" 1000.1;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "top";
	setAttr ".den" -type "string" "top_depth";
	setAttr ".man" -type "string" "top_mask";
	setAttr ".hc" -type "string" "viewSet -t %camera";
	setAttr ".o" yes;
	setAttr ".ai_translator" -type "string" "orthographic";
createNode transform -s -n "front";
	rename -uid "7F15B043-4418-7BD7-2940-B1BBAC2D22EF";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 0 0 1000.1 ;
createNode camera -s -n "frontShape" -p "front";
	rename -uid "280229F4-4529-8182-A9B3-A4AB77E6F2D5";
	setAttr -k off ".v" no;
	setAttr ".rnd" no;
	setAttr ".coi" 1000.1;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "front";
	setAttr ".den" -type "string" "front_depth";
	setAttr ".man" -type "string" "front_mask";
	setAttr ".hc" -type "string" "viewSet -f %camera";
	setAttr ".o" yes;
	setAttr ".ai_translator" -type "string" "orthographic";
createNode transform -s -n "side";
	rename -uid "6D009272-4A0C-404B-30A9-229D02D69D7C";
	setAttr ".v" no;
	setAttr ".t" -type "double3" 1000.1 0 0 ;
	setAttr ".r" -type "double3" 0 90 0 ;
createNode camera -s -n "sideShape" -p "side";
	rename -uid "98DB0690-49DC-1196-2BA3-EDB05EA8DF1B";
	setAttr -k off ".v" no;
	setAttr ".rnd" no;
	setAttr ".coi" 1000.1;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "side";
	setAttr ".den" -type "string" "side_depth";
	setAttr ".man" -type "string" "side_mask";
	setAttr ".hc" -type "string" "viewSet -s %camera";
	setAttr ".o" yes;
	setAttr ".ai_translator" -type "string" "orthographic";
createNode transform -n "mcpLight_key";
	rename -uid "40F38492-40A5-D7BE-D198-769588A24372";
	setAttr ".r" -type "double3" -35 29.999999999999986 1.8362941015152852e-15 ;
createNode directionalLight -n "mcpLight_keyShape" -p "mcpLight_key";
	rename -uid "12F97007-41DA-93A8-1E89-FD8ADF0DA746";
	setAttr -k off ".v";
	setAttr ".in" 2.0999999046325684;
createNode transform -n "mcpLight_fill";
	rename -uid "A1188C4E-4202-661F-A27F-5C8D23E0C1E8";
	setAttr ".r" -type "double3" -15.000000000000002 -55.000000000000021 1.386281966923813e-15 ;
createNode directionalLight -n "mcpLight_fillShape" -p "mcpLight_fill";
	rename -uid "E80B35D9-4F86-78B0-218D-D0A634C7654D";
	setAttr -k off ".v";
	setAttr ".in" 0.73500001430511475;
createNode transform -n "mcpLight_rim";
	rename -uid "6DF275B9-4D9A-AF06-2E05-2694D186FAF5";
	setAttr ".r" -type "double3" 170 15.000000000000009 180 ;
createNode directionalLight -n "mcpLight_rimShape" -p "mcpLight_rim";
	rename -uid "D2404CEE-4F54-0077-C239-268241D9C1A8";
	setAttr -k off ".v";
	setAttr ".in" 1.4700000286102295;
createNode transform -n "rotunda";
	rename -uid "9BB6BE8E-4EE1-F782-EC6C-8DA5E2A120CD";
	setAttr ".rp" -type "double3" -1.5497207641601562e-06 9.6000000000000014 -2.3245811462402344e-06 ;
	setAttr ".sp" -type "double3" -1.5497207641601562e-06 9.6000000000000014 -2.3245811462402344e-06 ;
createNode transform -n "stylobate" -p "rotunda";
	rename -uid "375D940B-43EB-416A-0AEB-08BAED110377";
	setAttr ".t" -type "double3" 0 1.45 0 ;
	setAttr ".s" -type "double3" 21 0.5 21 ;
createNode mesh -n "stylobateShape" -p "stylobate";
	rename -uid "DA4EFE0C-4AC3-5889-BA23-1EBE0F7A4142";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "innerFloor" -p "rotunda";
	rename -uid "B3047EF3-412F-ED7D-81B5-2A976ED3A194";
	setAttr ".t" -type "double3" 0 1.72 0 ;
	setAttr ".s" -type "double3" 17.5 0.15 17.5 ;
createNode mesh -n "innerFloorShape" -p "innerFloor";
	rename -uid "B6E39DB6-49DF-58E0-73C1-5AB551C868A8";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "architrave" -p "rotunda";
	rename -uid "4FA21984-47AA-5874-5B67-B38A248B76E6";
	setAttr ".t" -type "double3" 0 10.15 0 ;
	setAttr ".s" -type "double3" 19.6 1 19.6 ;
createNode mesh -n "architraveShape" -p "architrave";
	rename -uid "A0C3148B-42B9-B47B-7E54-38A22A018B43";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "cornice" -p "rotunda";
	rename -uid "BC76B400-4D82-40EB-9E2C-9DBB9B135B86";
	setAttr ".t" -type "double3" 0 10.95 0 ;
	setAttr ".s" -type "double3" 20.8 0.6 20.8 ;
createNode mesh -n "corniceShape" -p "cornice";
	rename -uid "C33B3E78-46D4-043E-78E5-6D899FD64D8F";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "finial" -p "rotunda";
	rename -uid "7E34D206-4A14-CDD3-88C1-ED95A72612DA";
	setAttr ".t" -type "double3" 0 17.6 0 ;
	setAttr ".s" -type "double3" 2 3.2 2 ;
createNode mesh -n "finialShape" -p "finial";
	rename -uid "959C0B3D-4CB4-2382-0697-7DA582BB5DF3";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 10 ".uvst[0].uvsp[0:9]" -type "float2" 0.5714286 0 0.14285715
		 0.33333334 0.42857146 0.33333334 0.71428573 0.33333334 1 0.33333334 0 0.66666669
		 0.2857143 0.66666669 0.5714286 0.66666669 0.85714293 0.66666669 0.42857146 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 6 ".vt[0:5]"  0 0.5 0 0.5 0 0 0 0 -0.5 -0.5 0 0 0 0 0.5
		 0 -0.5 0;
	setAttr -s 12 ".ed[0:11]"  1 2 1 2 0 1 0 1 1 2 3 1 3 0 1 3 4 1 4 0 1
		 4 1 1 5 2 1 1 5 1 5 3 1 5 4 1;
	setAttr -s 8 -ch 24 ".fc[0:7]" -type "polyFaces" 
		f 3 0 1 2
		mu 0 3 6 1 2
		f 3 3 4 -2
		mu 0 3 0 3 2
		f 3 5 6 -5
		mu 0 3 3 7 2
		f 3 -7 7 -3
		mu 0 3 2 7 6
		f 3 8 -1 9
		mu 0 3 5 1 6
		f 3 10 -4 -9
		mu 0 3 8 3 4
		f 3 11 -6 -11
		mu 0 3 8 7 3
		f 3 -10 -8 -12
		mu 0 3 9 6 7;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "altar" -p "rotunda";
	rename -uid "0C21FF41-451B-DEE9-15EA-D6949F209CBD";
	setAttr ".t" -type "double3" 0 2.15 0 ;
	setAttr ".s" -type "double3" 4.2 1 4.2 ;
createNode mesh -n "altarShape" -p "altar";
	rename -uid "9EDDDD95-49C8-9FBA-5092-4CBA3498EF39";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "gem" -p "rotunda";
	rename -uid "446F8996-45B5-5EF8-3FB9-2D9653BF1297";
	setAttr ".t" -type "double3" 0 4.6 0 ;
	setAttr ".r" -type "double3" 0 29.999999999999996 0 ;
	setAttr ".s" -type "double3" 3.8 5.2 3.8 ;
createNode mesh -n "gemShape" -p "gem";
	rename -uid "C5C9D1DC-4C8E-540C-7246-D891CD94DA5B";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 10 ".uvst[0].uvsp[0:9]" -type "float2" 0.5714286 0 0.14285715
		 0.33333334 0.42857146 0.33333334 0.71428573 0.33333334 1 0.33333334 0 0.66666669
		 0.2857143 0.66666669 0.5714286 0.66666669 0.85714293 0.66666669 0.42857146 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 6 ".vt[0:5]"  0 0.5 0 0.5 0 0 0 0 -0.5 -0.5 0 0 0 0 0.5
		 0 -0.5 0;
	setAttr -s 12 ".ed[0:11]"  1 2 1 2 0 1 0 1 1 2 3 1 3 0 1 3 4 1 4 0 1
		 4 1 1 5 2 1 1 5 1 5 3 1 5 4 1;
	setAttr -s 8 -ch 24 ".fc[0:7]" -type "polyFaces" 
		f 3 0 1 2
		mu 0 3 6 1 2
		f 3 3 4 -2
		mu 0 3 0 3 2
		f 3 5 6 -5
		mu 0 3 3 7 2
		f 3 -7 7 -3
		mu 0 3 2 7 6
		f 3 8 -1 9
		mu 0 3 5 1 6
		f 3 10 -4 -9
		mu 0 3 8 3 4
		f 3 11 -6 -11
		mu 0 3 8 7 3
		f 3 -10 -8 -12
		mu 0 3 9 6 7;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "dome" -p "rotunda";
	rename -uid "314F62F0-47DB-56ED-7318-4384C997DE69";
	setAttr ".rp" -type "double3" -9.5367431640625e-07 13.950000286102295 -1.430511474609375e-06 ;
	setAttr ".sp" -type "double3" -9.5367431640625e-07 13.950000286102295 -1.430511474609375e-06 ;
createNode mesh -n "domeShape" -p "dome";
	rename -uid "1271700F-4500-27A3-6319-228D74F26872";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 7 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "back";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 0;
	setAttr ".gtag[1].gtagnm" -type "string" "booleanIntersection";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 15 "e[13]" "e[17]" "e[38:39]" "e[71:72]" "e[161]" "e[166]" "e[228]" "e[233]" "e[286]" "e[291]" "e[340]" "e[342]" "e[372:373]" "e[379]" "e[395:397]";
	setAttr ".gtag[2].gtagnm" -type "string" "bottom";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 0;
	setAttr ".gtag[3].gtagnm" -type "string" "front";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 0;
	setAttr ".gtag[4].gtagnm" -type "string" "left";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 0;
	setAttr ".gtag[5].gtagnm" -type "string" "right";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 0;
	setAttr ".gtag[6].gtagnm" -type "string" "top";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "f[197]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 250 ".uvst[0].uvsp[0:249]" -type "float2" 0.35000002 0.55000007
		 0.35000002 0.60000008 0.30000001 0.60000008 0.30000001 0.55000007 0.25 0.60000008
		 0.25 0.55000007 0.40000004 0.55000007 0.40000004 0.60000008 0.25 0.50000006 0.2 0.55000007
		 0.2 0.50000006 0.45000005 0.50000006 0.45000005 0.55000007 0.40000004 0.50000006
		 0.35000002 0.6500001 0.30000001 0.6500001 0.25 0.6500001 0.40000004 0.6500001 0.2
		 0.60000008 0.45000005 0.60000008 0.35000002 0.70000011 0.30000001 0.70000011 0.2
		 0.6500001 0.45000005 0.6500001 0.15000001 0.55000007 0.15000001 0.50000006 0.50000006
		 0.50000006 0.50000006 0.55000007 0.25 0.70000011 0.40000004 0.70000011 0.15000001
		 0.60000008 0.50000006 0.60000008 0.35000002 0.75000012 0.30000001 0.75000012 0.2
		 0.70000011 0.45000005 0.70000011 0.25 0.75000012 0.40000004 0.75000012 0.15000001
		 0.6500001 0.50000006 0.6500001 0.2 0.75000012 0.45000005 0.75000012 0.1 0.55000007
		 0.1 0.50000006 0.55000007 0.50000006 0.55000007 0.55000007 0.35000002 0.80000013
		 0.30000001 0.80000013 0.15000001 0.70000011 0.50000006 0.70000011 0.25 0.80000013
		 0.40000004 0.80000013 0.1 0.60000008 0.55000007 0.60000008 0.35000002 0.95000017
		 0.32500002 1 0.30000001 0.95000017 0.27500001 1 0.25 0.95000017 0.40000004 0.95000017
		 0.375 1 0.2 0.80000013 0.45000005 0.80000013 0.22500001 1 0.2 0.95000017 0.45000005
		 0.95000017 0.42500001 1 0.17500001 1 0.15000001 0.95000017 0.50000006 0.95000017
		 0.47500002 1 0.15000001 0.75000012 0.50000006 0.75000012 0.125 1 0.1 0.95000017 0.55000007
		 0.95000017 0.52499998 1 0.1 0.6500001 0.55000007 0.6500001 0.60000008 0.95000017
		 0.57499999 1 0.075000003 1 0.050000001 0.95000017 0.35000002 0.85000014 0.30000001
		 0.85000014 0.6500001 0.95000017 0.625 1 0.025 1 0 0.95000017 0.25 0.85000014 0.40000004
		 0.85000014 0.70000011 0.95000017 0.67500001 1 0.97499996 1 0.95000017 0.95000017
		 1.000000119209 0.95000017 0.92500001 1 0.90000015 0.95000017 0.75000012 0.95000017
		 0.72499996 1 0.77499998 1 0.80000013 0.95000017 0.875 1 0.85000014 0.95000017 0.82499999
		 1 0.1 0.70000011 0.55000007 0.70000011 0.15000001 0.80000013 0.50000006 0.80000013
		 0.2 0.85000014 0.45000005 0.85000014 0.60000008 0.50000006 0.60000008 0.55000007
		 0.050000001 0.55000007 0.050000001 0.50000006 0.35000002 0.90000015 0.30000001 0.90000015
		 0.1 0.75000012 0.55000007 0.75000012 0.25 0.90000015 0.40000004 0.90000015 0.60000008
		 0.60000008 0.050000001 0.60000008 0.15000001 0.85000014 0.50000006 0.85000014 0.2
		 0.90000015 0.45000005 0.90000015 0.1 0.80000013 0.55000007 0.80000013 0.60000008
		 0.6500001 0.050000001 0.6500001 0.75000012 0.60000008 0.75000012 0.55000007 0.80000007
		 0.55000007 0.8500002 0.60000008 0.90000021 0.55000007 0.90000015 0.60000008 0.85000014
		 0.55000007 0.80000013 0.60000008 0.15000001 0.90000015 0.50000006 0.90000015 0.60000008
		 0.70000011 0.050000001 0.70000011 0.1 0.85000014 0.55000007 0.85000014 0.60000008
		 0.75000012 0.050000001 0.75000012 0.6500001 0.50000006 0.6500001 0.55000007 0 0.55000007
		 0 0.50000006 0.1 0.90000015 0.55000007 0.90000015 0.60000008 0.80000013 0.050000001
		 0.80000013 0.6500001 0.60000008 0 0.60000008 0.60000008 0.85000014 0.050000001 0.85000014
		 0.60000008 0.90000015 0.050000001 0.90000015 0.6500001 0.6500001 0 0.6500001 0.6500001
		 0.70000011 0 0.70000011 0.6500001 0.75000012 0 0.75000012 0.6500001 0.90000015 0
		 0.90000015 0.6500001 0.80000013 0 0.80000013 0.6500001 0.85000014 0 0.85000014 0.70000011
		 0.50000006 0.70000011 0.55000007 1.000000119209 0.55000007 0.95000017 0.55000007
		 0.95000017 0.50000006 1.000000119209 0.50000006 0.70000011 0.90000015 0.95000017
		 0.90000015 1.000000119209 0.90000015 0.90000015 0.90000015 0.75000012 0.90000015
		 0.70000011 0.60000008 1.000000119209 0.60000008 0.95000017 0.60000008 0.70000011
		 0.85000014 0.95000017 0.85000014 1.000000119209 0.85000014 0.80000013 0.90000015
		 0.85000014 0.90000015 0.70000011 0.6500001 1.000000119209 0.6500001 0.95000017 0.6500001
		 0.70000011 0.80000013 0.95000017 0.80000013 1.000000119209 0.80000013 0.70000011
		 0.70000011 1.000000119209 0.70000011 0.95000017 0.70000011 0.70000011 0.75000012
		 0.95000017 0.75000012 1.000000119209 0.75000012 0.90000015 0.85000014 0.75000012
		 0.85000014 0.85000014 0.85000014 0.80000013 0.85000014 0.90000015 0.50000006 0.75000012
		 0.50000006 0.90000015 0.80000013 0.75000012 0.80000013 0.90000015 0.75000012 0.75000012
		 0.75000012 0.85000014 0.80000013 0.80000013 0.80000013 0.90000015 0.6500001 0.75000012
		 0.6500001 0.90000015 0.70000011 0.75000012 0.70000011 0.85000014 0.50000006 0.80000013
		 0.50000006 0.80000013 0.75000012 0.85000014 0.75000012 0.85000014 0.70000011 0.80000013
		 0.70000011 0.85000014 0.6500001 0.80000013 0.6500001 0.42848486 0.375 0.43182191
		 0.39080203 0.44150642 0.40505719 0.45659041 0.41637021 0.47559732 0.42363361 0.49666673
		 0.42613637 0.51773602 0.42363361 0.53674299 0.41637021 0.55182695 0.40505722 0.56151146
		 0.39080203 0.56484848 0.375 0.56151146 0.35919797 0.55182695 0.34494281 0.53674299
		 0.33362979 0.51773602 0.32636642 0.49666667 0.32386363 0.47559735 0.32636642 0.45659041
		 0.33362979 0.44150642 0.34494281 0.43182188 0.35919797 0.35000002 0.50000006 0.30000001
		 0.50000006;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 201 ".vt";
	setAttr ".vt[0:165]"  -7.19151211 11.71682358 -5.22493935 -6.92479038 12.70861053 -5.031154633
		 -5.031155109 12.70861053 -6.92479086 -5.22493982 11.71682358 -7.19151258 -2.64503503 12.70861053 -8.14058018
		 -2.74691391 11.71682358 -8.45413113 -8.45412922 11.71682358 -2.74691296 -8.14057922 12.70861053 -2.64503431
		 -2.78115439 10.69999981 -8.55951309 0 11.71682358 -8.88919926 0 10.69999981 -9.000003814697
		 -9.000001907349 10.69999981 0 -8.88919735 11.71682358 0 -8.55951118 10.69999981 -2.78115368
		 -6.48755646 13.65093803 -4.71348572 -4.71348619 13.65093803 -6.48755693 -2.47802663 13.65093803 -7.62658167
		 -7.62658024 13.65093803 -2.47802591 0 12.70861053 -8.55951309 -8.55951118 12.70861053 0
		 -5.89057827 14.52060413 -4.27975559 -4.27975607 14.52060413 -5.89057875 0 13.65093803 -8.019062042
		 -8.019061089 13.65093803 0 2.74691391 11.71682358 -8.45413113 2.78115439 10.69999981 -8.55951309
		 -8.55951118 10.69999981 2.78115368 -8.45412922 11.71682358 2.74691296 -2.25000095 14.52060413 -6.92479086
		 -6.92478991 14.52060413 -2.25000048 2.64503503 12.70861053 -8.14058113 -8.14057922 12.70861053 2.64503431
		 -5.14855385 15.29619408 -3.7406435 -3.74064374 15.29619408 -5.14855433 0 14.52060413 -7.28115606
		 -7.28115463 14.52060413 0 -1.96657312 15.29619408 -6.052489281 -6.052488327 15.29619408 -1.9665724
		 2.47802663 13.65093803 -7.62658167 -7.62658024 13.65093803 2.47802591 0 15.29619408 -6.36396408
		 -6.36396265 15.29619408 0 5.22494125 11.71682358 -7.19151402 5.29007053 10.69999981 -7.28115749
		 -7.28115463 10.69999981 5.29006815 -7.19151163 11.71682358 5.22493887 -4.27975559 15.95861053 -3.10942435
		 -3.10942483 15.95861053 -4.27975559 2.25000095 14.52060413 -6.92479134 -6.92478991 14.52060413 2.25000048
		 -1.63472152 15.95861053 -5.031155109 -5.031154156 15.95861053 -1.63472092 5.031156063 12.70861053 -6.92479229
		 -6.92478991 12.70861053 5.031154156 -1.13902366 17.11997414 -0.8275491 0 17.20000076 0
		 -0.82754928 17.11997414 -1.13902378 -0.43506843 17.11997414 -1.33900285 -1.33900261 17.11997414 -0.43506831
		 0 15.95861053 -5.29007006 -5.29006815 15.95861053 0 0 17.11997414 -1.40791094 -1.4079107 17.11997414 0
		 0.43506843 17.11997414 -1.33900297 -1.33900261 17.11997414 0.43506831 1.96657312 15.29619408 -6.052489758
		 -6.052488327 15.29619408 1.9665724 0.8275494 17.11997414 -1.13902402 -1.13902366 17.11997414 0.82754904
		 4.71348715 13.65093803 -6.48755884 -6.48755646 13.65093803 4.71348572 -0.82754904 17.11997414 1.13902354
		 1.13902402 17.11997414 -0.8275494 -3.30557537 16.49154282 -2.40164113 -2.40164137 16.49154282 -3.30557561
		 -0.43506831 17.11997414 1.33900249 1.33900309 17.11997414 -0.43506849 -1.26261771 16.49154282 -3.88593745
		 -3.88593698 16.49154282 -1.26261735 -4.1958998e-08 17.11997414 1.40791047 1.40791035 17.11997414 0
		 1.33900237 17.11997414 0.43506822 0.43506819 17.11997414 1.33900237 0.82754892 17.11997414 1.13902342
		 1.13902342 17.11997414 0.82754898 4.27975702 14.52060413 -5.89058018 -5.89057779 14.52060413 4.27975512
		 1.63472152 15.95861053 -5.031155586 -5.031154156 15.95861053 1.63472092 0 16.49154282 -4.085916519
		 -4.085915565 16.49154282 0 -5.29006815 10.69999981 7.28115416 -5.22493887 11.71682358 7.19151115
		 7.19151449 11.71682358 -5.22494125 7.28115797 10.69999981 -5.29007053 -2.25000072 16.88186646 -1.63472128
		 -1.6347214 16.88186646 -2.25000072 3.74064469 15.29619408 -5.14855528 -5.14855385 15.29619408 3.74064302
		 -0.85942394 16.88186646 -2.64503503 -2.64503431 16.88186646 -0.85942376 -5.031154156 12.70861053 6.92478943
		 6.92479277 12.70861053 -5.031156063 1.26261771 16.49154282 -3.88593769 -3.88593698 16.49154282 1.26261735
		 0 16.88186646 -2.78115439 -2.78115368 16.88186646 0 3.10942531 15.95861053 -4.27975702
		 -4.27975512 15.95861053 3.10942411 -4.71348572 13.65093803 6.48755598 6.48755932 13.65093803 -4.71348715
		 2.6450336 12.70861053 8.14057732 2.74691224 11.71682358 8.45412827 5.22493792 11.71682358 7.1915102
		 6.92478848 12.70861053 5.031153679 8.45412731 11.71682358 2.74691248 8.14057636 12.70861053 2.64503384
		 7.19150972 11.71682358 5.22493839 5.031153202 12.70861053 6.92478895 0.85942394 16.88186646 -2.64503527
		 -2.64503431 16.88186646 0.85942376 -4.27975512 14.52060413 5.89057732 5.89058065 14.52060413 -4.27975702
		 2.40164185 16.49154282 -3.30557632 -3.30557513 16.49154282 2.40164089 -3.74064302 15.29619408 5.14855337
		 5.14855576 15.29619408 -3.74064469 -2.78115368 10.69999981 8.55951023 -2.74691296 11.71682358 8.45412827
		 8.45413208 11.71682358 -2.74691415 8.55951405 10.69999981 -2.78115463 1.63472164 16.88186646 -2.25000143
		 -2.25000048 16.88186646 1.63472104 -3.10942411 15.95861053 4.27975512 4.27975702 15.95861053 -3.10942531
		 -2.64503431 12.70861053 8.14057827 8.14058208 12.70861053 -2.64503527 -2.40164089 16.49154282 3.30557513
		 3.30557656 16.49154282 -2.40164185 -1.63472104 16.88186646 2.25000048 2.25000167 16.88186646 -1.63472164
		 -2.47802591 13.65093803 7.62657928 7.6265831 13.65093803 -2.47802687 -2.25000048 14.52060413 6.92478895
		 6.92479277 14.52060413 -2.25000143 -1.9665724 15.29619408 6.052487373 6.052490234 15.29619408 -1.96657324
		 -0.85942376 16.88186646 2.64503407 2.64503551 16.88186646 -0.85942411 -1.63472092 15.95861053 5.031153679
		 5.031156063 15.95861053 -1.63472164 -1.26261735 16.49154282 3.8859365 3.88593817 16.49154282 -1.26261783
		 -2.682209e-07 10.69999981 9.000000953674 -2.6491867e-07 11.71682358 8.8891964 8.88919544 11.71682358 0
		 9 10.69999981 0 -8.2884817e-08 16.88186646 2.7811532 2.78115296 16.88186646 0 2.64503384 16.88186646 0.85942358
		 0.85942352 16.88186646 2.64503384 -2.5509325e-07 12.70861053 8.55951023 8.55950928 12.70861053 0
		 -1.2176974e-07 16.49154282 4.085915089 4.085914612 16.49154282 0 1.63472068 16.88186646 2.25000024;
	setAttr ".vt[166:200]" 2.25 16.88186646 1.6347208 -2.3898659e-07 13.65093803 8.019060135
		 8.019059181 13.65093803 0 -1.5765629e-07 15.95861053 5.29006767 5.2900672 15.95861053 0
		 -2.1699528e-07 14.52060413 7.28115416 7.2811532 14.52060413 0 -1.8966081e-07 15.29619408 6.36396122
		 6.36396074 15.29619408 0 3.88593578 16.49154282 1.26261711 1.26261699 16.49154282 3.88593626
		 3.30557442 16.49154282 2.40164065 2.40164042 16.49154282 3.30557489 8.55950928 10.69999981 2.78115296
		 2.78115273 10.69999981 8.55950928 5.031153202 15.95861053 1.63472068 1.63472056 15.95861053 5.031153679
		 6.052486897 15.29619408 1.96657217 1.96657193 15.29619408 6.052487373 4.27975464 15.95861053 3.10942364
		 3.1094234 15.95861053 4.27975464 7.62657833 13.65093803 2.47802567 2.47802544 13.65093803 7.62657881
		 6.92478848 14.52060413 2.25 2.24999976 14.52060413 6.92478895 7.2811532 10.69999981 5.29006767
		 5.2900672 10.69999981 7.28115368 3.74064231 15.29619408 5.14855289 5.14855289 15.29619408 3.74064279
		 5.89057684 14.52060413 4.27975464 4.27975464 14.52060413 5.89057684 6.48755503 13.65093803 4.71348524
		 4.71348476 13.65093803 6.4875555 -7.28115511 10.69999981 -5.29006863 -5.29006958 10.69999981 -7.28115559;
	setAttr -s 400 ".ed";
	setAttr ".ed[0:165]"  0 1 1 1 2 1 2 3 1 3 0 1 2 4 1 4 5 1 5 3 1 6 7 1 7 1 1
		 0 6 1 8 5 1 5 9 1 9 10 1 10 8 0 11 12 1 12 6 1 6 13 1 13 11 0 1 14 1 14 15 1 15 2 1
		 15 16 1 16 4 1 7 17 1 17 14 1 4 18 1 18 9 1 12 19 1 19 7 1 14 20 1 20 21 1 21 15 1
		 16 22 1 22 18 1 19 23 1 23 17 1 9 24 1 24 25 1 25 10 0 11 26 0 26 27 1 27 12 1 21 28 1
		 28 16 1 17 29 1 29 20 1 18 30 1 30 24 1 27 31 1 31 19 1 20 32 1 32 33 1 33 21 1 28 34 1
		 34 22 1 23 35 1 35 29 1 33 36 1 36 28 1 29 37 1 37 32 1 22 38 1 38 30 1 31 39 1 39 23 1
		 36 40 1 40 34 1 35 41 1 41 37 1 24 42 1 42 43 1 43 25 0 26 44 0 44 45 1 45 27 1 32 46 1
		 46 47 1 47 33 1 34 48 1 48 38 1 39 49 1 49 35 1 47 50 1 50 36 1 37 51 1 51 46 1 30 52 1
		 52 42 1 45 53 1 53 31 1 54 55 1 55 56 1 56 54 1 55 57 1 57 56 1 58 55 1 54 58 1 50 59 1
		 59 40 1 41 60 1 60 51 1 55 61 1 61 57 1 62 55 1 58 62 1 55 63 1 63 61 1 62 64 1 64 55 1
		 40 65 1 65 48 1 49 66 1 66 41 1 55 67 1 67 63 1 64 68 1 68 55 1 38 69 1 69 52 1 53 70 1
		 70 39 1 68 71 1 71 55 1 55 72 1 72 67 1 46 73 1 73 74 1 74 47 1 71 75 1 75 55 1 55 76 1
		 76 72 1 74 77 1 77 50 1 51 78 1 78 73 1 75 79 1 79 55 1 55 80 1 80 76 1 55 81 1 81 80 1
		 79 82 1 82 55 1 82 83 1 83 55 1 55 84 1 84 81 1 83 84 1 48 85 1 85 69 1 70 86 1 86 49 1
		 59 87 1 87 65 1 66 88 1 88 60 1 77 89 1 89 59 1 60 90 1 90 78 1 44 91 0 91 92 1 92 45 1
		 42 93 1 93 94 1;
	setAttr ".ed[166:331]" 94 43 0 73 95 1 95 96 1 96 74 1 65 97 1 97 85 1 86 98 1
		 98 66 1 96 99 1 99 77 1 78 100 1 100 95 1 92 101 1 101 53 1 52 102 1 102 93 1 89 103 1
		 103 87 1 88 104 1 104 90 1 99 105 1 105 89 1 90 106 1 106 100 1 87 107 1 107 97 1
		 98 108 1 108 88 1 101 109 1 109 70 1 69 110 1 110 102 1 111 112 1 112 113 1 115 116 1
		 116 114 1 114 117 1 117 115 1 113 118 1 118 111 1 105 119 1 119 103 1 104 120 1 120 106 1
		 95 54 1 56 96 1 109 121 1 121 86 1 85 122 1 122 110 1 103 123 1 123 107 1 108 124 1
		 124 104 1 57 99 1 100 58 1 61 105 1 106 62 1 121 125 1 125 98 1 97 126 1 126 122 1
		 91 127 0 127 128 1 128 92 1 93 129 1 129 130 1 130 94 0 119 131 1 131 123 1 124 132 1
		 132 120 1 63 119 1 120 64 1 125 133 1 133 108 1 107 134 1 134 126 1 128 135 1 135 101 1
		 102 136 1 136 129 1 67 131 1 132 68 1 133 137 1 137 124 1 123 138 1 138 134 1 137 139 1
		 139 132 1 131 140 1 140 138 1 135 141 1 141 109 1 110 142 1 142 136 1 139 71 1 72 140 1
		 141 143 1 143 121 1 122 144 1 144 142 1 143 145 1 145 125 1 126 146 1 146 144 1 139 147 1
		 147 75 1 76 148 1 148 140 1 145 149 1 149 133 1 134 150 1 150 146 1 137 151 1 151 147 1
		 148 152 1 152 138 1 149 151 1 152 150 1 127 153 0 153 154 1 154 128 1 129 155 1 155 156 1
		 156 130 0 147 157 1 157 79 1 80 158 1 158 148 1 81 159 1 159 158 1 157 160 1 160 82 1
		 154 161 1 161 135 1 136 162 1 162 155 1 151 163 1 163 157 1 158 164 1 164 152 1 160 165 1
		 165 83 1 84 166 1 166 159 1 165 166 1 161 167 1 167 141 1 142 168 1 168 162 1 149 169 1
		 169 163 1 164 170 1 170 150 1 167 171 1 171 143 1 144 172 1 172 168 1 145 173 1 173 169 1
		 170 174 1 174 146 1 171 173 1 174 172 1 159 175 1;
	setAttr ".ed[332:399]" 175 164 1 163 176 1 176 160 1 166 177 1 177 175 1 176 178 1
		 178 165 1 115 179 1 179 156 0 155 115 1 153 180 0 180 112 1 112 154 1 178 177 1 175 181 1
		 181 170 1 169 182 1 182 176 1 162 116 1 111 161 1 181 183 1 183 174 1 173 184 1 184 182 1
		 177 185 1 185 181 1 182 186 1 186 178 1 187 116 1 168 187 1 111 188 1 188 167 1 183 189 1
		 189 172 1 171 190 1 190 184 1 189 187 1 188 190 1 186 185 1 117 191 1 191 179 0 180 192 0
		 192 113 1 184 193 1 193 186 1 185 194 1 194 183 1 192 191 0 117 113 1 193 194 1 194 195 1
		 195 189 1 190 196 1 196 193 1 197 114 1 187 197 1 118 198 1 198 188 1 195 197 1 198 196 1
		 114 118 1 196 195 1 197 198 1 13 199 0 199 200 0 200 8 0 0 199 1 200 3 1;
	setAttr -s 201 -ch 800 ".fc[0:200]" -type "polyFaces" 
		f 4 0 1 2 3
		mu 0 4 0 1 2 3
		f 4 -3 4 5 6
		mu 0 4 3 2 4 5
		f 4 7 8 -1 9
		mu 0 4 6 7 1 0
		f 4 10 11 12 13
		mu 0 4 8 5 9 10
		f 4 14 15 16 17
		mu 0 4 11 12 6 13
		f 4 18 19 20 -2
		mu 0 4 1 14 15 2
		f 4 -21 21 22 -5
		mu 0 4 2 15 16 4
		f 4 23 24 -19 -9
		mu 0 4 7 17 14 1
		f 4 -6 25 26 -12
		mu 0 4 5 4 18 9
		f 4 27 28 -8 -16
		mu 0 4 12 19 7 6
		f 4 29 30 31 -20
		mu 0 4 14 20 21 15
		f 4 -23 32 33 -26
		mu 0 4 4 16 22 18
		f 4 34 35 -24 -29
		mu 0 4 19 23 17 7
		f 4 -13 36 37 38
		mu 0 4 10 9 24 25
		f 4 39 40 41 -15
		mu 0 4 11 26 27 12
		f 4 -32 42 43 -22
		mu 0 4 15 21 28 16
		f 4 44 45 -30 -25
		mu 0 4 17 29 20 14
		f 4 -27 46 47 -37
		mu 0 4 9 18 30 24
		f 4 -42 48 49 -28
		mu 0 4 12 27 31 19
		f 4 50 51 52 -31
		mu 0 4 20 32 33 21
		f 4 -44 53 54 -33
		mu 0 4 16 28 34 22
		f 4 55 56 -45 -36
		mu 0 4 23 35 29 17
		f 4 -53 57 58 -43
		mu 0 4 21 33 36 28
		f 4 59 60 -51 -46
		mu 0 4 29 37 32 20
		f 4 -34 61 62 -47
		mu 0 4 18 22 38 30
		f 4 -50 63 64 -35
		mu 0 4 19 31 39 23
		f 4 -59 65 66 -54
		mu 0 4 28 36 40 34
		f 4 67 68 -60 -57
		mu 0 4 35 41 37 29
		f 4 69 70 71 -38
		mu 0 4 24 42 43 25
		f 4 72 73 74 -41
		mu 0 4 26 44 45 27
		f 4 75 76 77 -52
		mu 0 4 32 46 47 33
		f 4 -55 78 79 -62
		mu 0 4 22 34 48 38
		f 4 -65 80 81 -56
		mu 0 4 23 39 49 35
		f 4 -78 82 83 -58
		mu 0 4 33 47 50 36
		f 4 84 85 -76 -61
		mu 0 4 37 51 46 32
		f 4 86 87 -70 -48
		mu 0 4 30 52 42 24
		f 4 -75 88 89 -49
		mu 0 4 27 45 53 31
		f 3 90 91 92
		mu 0 3 54 55 56
		f 3 -92 93 94
		mu 0 3 56 57 58
		f 3 95 -91 96
		mu 0 3 59 60 54
		f 4 -84 97 98 -66
		mu 0 4 36 50 61 40
		f 4 99 100 -85 -69
		mu 0 4 41 62 51 37
		f 3 -94 101 102
		mu 0 3 58 63 64
		f 3 103 -96 104
		mu 0 3 65 66 59
		f 3 -102 105 106
		mu 0 3 64 67 68
		f 3 107 108 -104
		mu 0 3 65 69 70
		f 4 -67 109 110 -79
		mu 0 4 34 40 71 48
		f 4 -82 111 112 -68
		mu 0 4 35 49 72 41
		f 3 113 114 -106
		mu 0 3 73 74 68
		f 3 115 116 -109
		mu 0 3 69 75 76
		f 4 117 118 -87 -63
		mu 0 4 38 77 52 30
		f 4 -90 119 120 -64
		mu 0 4 31 53 78 39
		f 3 121 122 -117
		mu 0 3 75 79 80
		f 3 123 124 -114
		mu 0 3 81 82 74
		f 4 125 126 127 -77
		mu 0 4 46 83 84 47
		f 3 128 129 -123
		mu 0 3 79 85 86
		f 3 130 131 -124
		mu 0 3 87 88 82
		f 4 -128 132 133 -83
		mu 0 4 47 84 89 50
		f 4 134 135 -126 -86
		mu 0 4 51 90 83 46
		f 3 136 137 -130
		mu 0 3 85 91 92
		f 3 138 139 -131
		mu 0 3 93 94 95
		f 3 140 141 -139
		mu 0 3 96 97 94
		f 3 142 143 -138
		mu 0 3 91 98 99
		f 3 -144 144 145
		mu 0 3 100 98 101
		f 3 146 147 -141
		mu 0 3 102 103 97
		f 3 -146 148 -147
		mu 0 3 104 101 103
		f 4 149 150 -118 -80
		mu 0 4 48 105 77 38
		f 4 -121 151 152 -81
		mu 0 4 39 78 106 49
		f 4 -99 153 154 -110
		mu 0 4 40 61 107 71
		f 4 -113 155 156 -100
		mu 0 4 41 72 108 62
		f 4 -134 157 158 -98
		mu 0 4 50 89 109 61
		f 4 159 160 -135 -101
		mu 0 4 62 110 90 51
		f 4 161 162 163 -74
		mu 0 4 44 111 112 45
		f 4 164 165 166 -71
		mu 0 4 42 113 114 43
		f 4 167 168 169 -127
		mu 0 4 83 115 116 84
		f 4 170 171 -150 -111
		mu 0 4 71 117 105 48
		f 4 -153 172 173 -112
		mu 0 4 49 106 118 72
		f 4 -170 174 175 -133
		mu 0 4 84 116 119 89
		f 4 176 177 -168 -136
		mu 0 4 90 120 115 83
		f 4 -164 178 179 -89
		mu 0 4 45 112 121 53
		f 4 180 181 -165 -88
		mu 0 4 52 122 113 42
		f 4 -159 182 183 -154
		mu 0 4 61 109 123 107
		f 4 -157 184 185 -160
		mu 0 4 62 108 124 110
		f 4 -176 186 187 -158
		mu 0 4 89 119 125 109
		f 4 188 189 -177 -161
		mu 0 4 110 126 120 90
		f 4 190 191 -171 -155
		mu 0 4 107 127 117 71
		f 4 -174 192 193 -156
		mu 0 4 72 118 128 108
		f 4 -180 194 195 -120
		mu 0 4 53 121 129 78
		f 4 196 197 -181 -119
		mu 0 4 77 130 122 52
		f 4 198 199 204 205
		mu 0 4 131 132 133 138
		f 4 200 201 202 203
		mu 0 4 135 136 134 137
		f 4 -188 206 207 -183
		mu 0 4 109 125 139 123
		f 4 -186 208 209 -189
		mu 0 4 110 124 140 126
		f 4 210 -93 211 -169
		mu 0 4 115 54 56 116
		f 4 -196 212 213 -152
		mu 0 4 78 129 141 106
		f 4 214 215 -197 -151
		mu 0 4 105 142 130 77
		f 4 216 217 -191 -184
		mu 0 4 123 143 127 107
		f 4 -194 218 219 -185
		mu 0 4 108 128 144 124
		f 4 -212 -95 220 -175
		mu 0 4 116 56 58 119
		f 4 221 -97 -211 -178
		mu 0 4 120 59 54 115
		f 4 -221 -103 222 -187
		mu 0 4 119 58 64 125
		f 4 223 -105 -222 -190
		mu 0 4 126 65 59 120
		f 4 -214 224 225 -173
		mu 0 4 106 141 145 118
		f 4 226 227 -215 -172
		mu 0 4 117 146 142 105
		f 4 228 229 230 -163
		mu 0 4 111 147 148 112
		f 4 231 232 233 -166
		mu 0 4 113 149 150 114
		f 4 234 235 -217 -208
		mu 0 4 139 151 143 123
		f 4 -220 236 237 -209
		mu 0 4 124 144 152 140
		f 4 -223 -107 238 -207
		mu 0 4 125 64 68 139
		f 4 -210 239 -108 -224
		mu 0 4 126 140 69 65
		f 4 -226 240 241 -193
		mu 0 4 118 145 153 128
		f 4 242 243 -227 -192
		mu 0 4 127 154 146 117
		f 4 -231 244 245 -179
		mu 0 4 112 148 155 121
		f 4 246 247 -232 -182
		mu 0 4 122 156 149 113
		f 4 -115 248 -235 -239
		mu 0 4 68 74 151 139
		f 4 -238 249 -116 -240
		mu 0 4 140 152 75 69
		f 4 -242 250 251 -219
		mu 0 4 128 153 157 144
		f 4 252 253 -243 -218
		mu 0 4 143 158 154 127
		f 4 -252 254 255 -237
		mu 0 4 144 157 159 152
		f 4 256 257 -253 -236
		mu 0 4 151 160 158 143
		f 4 -246 258 259 -195
		mu 0 4 121 155 161 129
		f 4 260 261 -247 -198
		mu 0 4 130 162 156 122
		f 4 -256 262 -122 -250
		mu 0 4 152 159 79 75
		f 4 -125 263 -257 -249
		mu 0 4 74 82 160 151
		f 4 -260 264 265 -213
		mu 0 4 129 161 163 141
		f 4 266 267 -261 -216
		mu 0 4 142 164 162 130
		f 4 -266 268 269 -225
		mu 0 4 141 163 165 145
		f 4 270 271 -267 -228
		mu 0 4 146 166 164 142
		f 4 272 273 -129 -263
		mu 0 4 159 167 85 79
		f 4 -132 274 275 -264
		mu 0 4 82 88 168 160
		f 4 -270 276 277 -241
		mu 0 4 145 165 169 153
		f 4 278 279 -271 -244
		mu 0 4 154 170 166 146
		f 4 280 281 -273 -255
		mu 0 4 157 171 167 159
		f 4 -276 282 283 -258
		mu 0 4 160 168 172 158
		f 4 -278 284 -281 -251
		mu 0 4 153 169 171 157
		f 4 -284 285 -279 -254
		mu 0 4 158 172 170 154
		f 4 286 287 288 -230
		mu 0 4 147 173 174 148
		f 4 289 290 291 -233
		mu 0 4 175 176 177 178
		f 4 292 293 -137 -274
		mu 0 4 167 179 91 85
		f 4 -140 294 295 -275
		mu 0 4 95 94 180 181
		f 4 296 297 -295 -142
		mu 0 4 97 182 180 94
		f 4 298 299 -143 -294
		mu 0 4 179 183 98 91
		f 4 -289 300 301 -245
		mu 0 4 148 174 184 155
		f 4 302 303 -290 -248
		mu 0 4 185 186 176 175
		f 4 304 305 -293 -282
		mu 0 4 171 187 179 167
		f 4 -296 306 307 -283
		mu 0 4 181 180 188 189
		f 4 -300 308 309 -145
		mu 0 4 98 183 190 101
		f 4 310 311 -297 -148
		mu 0 4 103 191 182 97
		f 4 -310 312 -311 -149
		mu 0 4 101 190 191 103
		f 4 -302 313 314 -259
		mu 0 4 155 184 192 161
		f 4 315 316 -303 -262
		mu 0 4 193 194 186 185
		f 4 317 318 -305 -285
		mu 0 4 169 195 187 171
		f 4 -308 319 320 -286
		mu 0 4 189 188 196 197
		f 4 -315 321 322 -265
		mu 0 4 161 192 198 163
		f 4 323 324 -316 -268
		mu 0 4 199 200 194 193
		f 4 325 326 -318 -277
		mu 0 4 165 201 195 169
		f 4 -321 327 328 -280
		mu 0 4 197 196 202 203
		f 4 -323 329 -326 -269
		mu 0 4 163 198 201 165
		f 4 -329 330 -324 -272
		mu 0 4 203 202 200 199
		f 4 331 332 -307 -298
		mu 0 4 182 204 188 180
		f 4 333 334 -299 -306
		mu 0 4 187 205 183 179
		f 4 335 336 -332 -312
		mu 0 4 191 206 204 182
		f 4 -335 337 338 -309
		mu 0 4 183 205 207 190
		f 4 339 340 -291 341
		mu 0 4 135 208 177 176
		f 4 342 343 344 -288
		mu 0 4 173 209 132 174
		f 4 -339 345 -336 -313
		mu 0 4 190 207 206 191
		f 4 346 347 -320 -333
		mu 0 4 204 210 196 188
		f 4 348 349 -334 -319
		mu 0 4 195 211 205 187
		f 4 -201 -342 -304 350
		mu 0 4 136 135 176 186
		f 4 -345 -199 351 -301
		mu 0 4 174 132 131 184
		f 4 352 353 -328 -348
		mu 0 4 210 212 202 196
		f 4 354 355 -349 -327
		mu 0 4 201 213 211 195
		f 4 356 357 -347 -337
		mu 0 4 206 214 210 204
		f 4 -350 358 359 -338
		mu 0 4 205 211 215 207
		f 4 360 -351 -317 361
		mu 0 4 216 136 186 194
		f 4 -352 362 363 -314
		mu 0 4 184 131 217 192
		f 4 364 365 -331 -354
		mu 0 4 212 218 200 202
		f 4 366 367 -355 -330
		mu 0 4 198 219 213 201
		f 4 368 -362 -325 -366
		mu 0 4 218 216 194 200
		f 4 -364 369 -367 -322
		mu 0 4 192 217 219 198
		f 4 -360 370 -357 -346
		mu 0 4 207 215 214 206
		f 4 371 372 -340 -204
		mu 0 4 137 220 208 135
		f 4 -344 373 374 -200
		mu 0 4 132 209 221 133
		f 4 -356 375 376 -359
		mu 0 4 211 213 222 215
		f 4 377 378 -353 -358
		mu 0 4 214 223 212 210
		f 4 -375 379 -372 380
		mu 0 4 133 221 220 137
		f 4 -377 381 -378 -371
		mu 0 4 215 222 223 214
		f 4 382 383 -365 -379
		mu 0 4 223 224 218 212
		f 4 -368 384 385 -376
		mu 0 4 213 219 225 222
		f 4 386 -202 -361 387
		mu 0 4 226 134 136 216
		f 4 -363 -206 388 389
		mu 0 4 217 131 138 227
		f 4 390 -388 -369 -384
		mu 0 4 224 226 216 218
		f 4 -370 -390 391 -385
		mu 0 4 219 217 227 225
		f 4 -205 -381 -203 392
		mu 0 4 138 133 137 134
		f 4 -386 393 -383 -382
		mu 0 4 222 225 224 223
		f 4 -389 -393 -387 394
		mu 0 4 227 138 134 226
		f 4 -392 -395 -391 -394
		mu 0 4 225 227 226 224
		f 20 -18 395 396 397 -14 -39 -72 -167 -234 -292 -341 -373 -380 -374 -343 -287 -229 -162
		 -73 -40
		mu 0 20 228 229 230 231 232 233 234 235 236 237 238 239 240 241 242 243 244 245 246 247
		f 4 -17 -10 398 -396
		mu 0 4 13 6 0 248
		f 4 399 -7 -11 -398
		mu 0 4 249 3 5 8
		f 4 -399 -4 -400 -397
		mu 0 4 248 0 3 249;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "step_base" -p "rotunda";
	rename -uid "34A4CD2C-439E-F904-04E2-338E56186C37";
	setAttr ".t" -type "double3" 0 0.2 0 ;
	setAttr ".s" -type "double3" 26 0.4 26 ;
createNode mesh -n "step_baseShape" -p "step_base";
	rename -uid "001CACB9-49B8-9416-BE1C-BFB635B61C34";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "step_1" -p "rotunda";
	rename -uid "0215EA6D-4A03-40D2-F87F-B6BFFD8B6B86";
	setAttr ".t" -type "double3" 0 0.60000000000000009 0 ;
	setAttr ".s" -type "double3" 24.18 0.4 24.18 ;
createNode mesh -n "step_1Shape" -p "step_1";
	rename -uid "6461245E-4A5C-7CFF-9165-9EB458D80C53";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "step_2" -p "rotunda";
	rename -uid "8BFA42DB-41D9-A8E6-EAD1-09AAC10EC096";
	setAttr ".t" -type "double3" 0 1 0 ;
	setAttr ".s" -type "double3" 22.487400000000004 0.4 22.487400000000004 ;
createNode mesh -n "step_2Shape" -p "step_2";
	rename -uid "B4D93D7A-466A-1506-15BB-73974A3B44F4";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[20]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:19]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:19]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[20:39]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:19]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[21]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[20:39]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 82 ".uvst[0].uvsp[0:81]" -type "float2" 0.97740829 0.086372852
		 0.90638852 0.0515268 0.79577255 0.023872823 0.65638828 0.0061178803 0.50187969 -5.9604645e-08
		 0.3473711 0.0061178803 0.20798695 0.023872837 0.097371072 0.051526815 0.026351303
		 0.086372867 0.0018795729 0.125 0.026351303 0.16362715 0.097371101 0.19847316 0.20798701
		 0.22612715 0.34737116 0.24388209 0.50187969 0.25 0.65638816 0.24388206 0.79577231
		 0.22612715 0.90638816 0.19847316 0.97740793 0.16362712 1.0018796921 0.125 0 0.25
		 0.050000001 0.25 0.1 0.25 0.15000001 0.25 0.2 0.25 0.25 0.25 0.30000001 0.25 0.35000002
		 0.25 0.40000004 0.25 0.45000005 0.25 0.50000006 0.25 0.55000007 0.25 0.60000008 0.25
		 0.6500001 0.25 0.70000011 0.25 0.75000012 0.25 0.80000013 0.25 0.85000014 0.25 0.90000015
		 0.25 0.95000017 0.25 1.000000119209 0.25 0 0.75 0.050000001 0.75 0.1 0.75 0.15000001
		 0.75 0.2 0.75 0.25 0.75 0.30000001 0.75 0.35000002 0.75 0.40000004 0.75 0.45000005
		 0.75 0.50000006 0.75 0.55000007 0.75 0.60000008 0.75 0.6500001 0.75 0.70000011 0.75
		 0.75000012 0.75 0.80000013 0.75 0.85000014 0.75 0.90000015 0.75 0.95000017 0.75 1.000000119209
		 0.75 0.97740829 0.83637285 0.90638852 0.80152678 0.79577255 0.77387285 0.65638828
		 0.75611788 0.50187969 0.74999994 0.3473711 0.75611788 0.20798695 0.77387285 0.097371072
		 0.80152678 0.026351303 0.83637285 0.0018795729 0.875 0.026351303 0.91362715 0.097371101
		 0.94847316 0.20798701 0.97612715 0.34737116 0.99388206 0.50187969 1 0.65638816 0.99388206
		 0.79577231 0.97612715 0.90638816 0.94847316 0.97740793 0.91362715 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 40 ".vt[0:39]"  0.47552857 -0.5 -0.15450859 0.40450877 -0.5 -0.2938928
		 0.2938928 -0.5 -0.40450874 0.15450858 -0.5 -0.47552851 0 -0.5 -0.50000024 -0.15450858 -0.5 -0.47552848
		 -0.29389274 -0.5 -0.40450865 -0.40450862 -0.5 -0.29389271 -0.47552839 -0.5 -0.15450853
		 -0.50000012 -0.5 0 -0.47552839 -0.5 0.15450853 -0.40450859 -0.5 0.29389268 -0.29389268 -0.5 0.40450856
		 -0.15450853 -0.5 0.47552833 -1.4901161e-08 -0.5 0.50000006 0.15450849 -0.5 0.4755283
		 0.29389262 -0.5 0.40450853 0.4045085 -0.5 0.29389265 0.47552827 -0.5 0.1545085 0.5 -0.5 0
		 0.47552857 0.5 -0.15450859 0.40450877 0.5 -0.2938928 0.2938928 0.5 -0.40450874 0.15450858 0.5 -0.47552851
		 0 0.5 -0.50000024 -0.15450858 0.5 -0.47552848 -0.29389274 0.5 -0.40450865 -0.40450862 0.5 -0.29389271
		 -0.47552839 0.5 -0.15450853 -0.50000012 0.5 0 -0.47552839 0.5 0.15450853 -0.40450859 0.5 0.29389268
		 -0.29389268 0.5 0.40450856 -0.15450853 0.5 0.47552833 -1.4901161e-08 0.5 0.50000006
		 0.15450849 0.5 0.4755283 0.29389262 0.5 0.40450853 0.4045085 0.5 0.29389265 0.47552827 0.5 0.1545085
		 0.5 0.5 0;
	setAttr -s 60 ".ed[0:59]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0
		 7 8 0 8 9 0 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0
		 18 19 0 19 0 0 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0
		 29 30 0 30 31 0 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 20 0
		 0 20 1 1 21 1 2 22 1 3 23 1 4 24 1 5 25 1 6 26 1 7 27 1 8 28 1 9 29 1 10 30 1 11 31 1
		 12 32 1 13 33 1 14 34 1 15 35 1 16 36 1 17 37 1 18 38 1 19 39 1;
	setAttr -s 22 -ch 120 ".fc[0:21]" -type "polyFaces" 
		f 4 0 41 -21 -41
		mu 0 4 20 21 42 41
		f 4 1 42 -22 -42
		mu 0 4 21 22 43 42
		f 4 2 43 -23 -43
		mu 0 4 22 23 44 43
		f 4 3 44 -24 -44
		mu 0 4 23 24 45 44
		f 4 4 45 -25 -45
		mu 0 4 24 25 46 45
		f 4 5 46 -26 -46
		mu 0 4 25 26 47 46
		f 4 6 47 -27 -47
		mu 0 4 26 27 48 47
		f 4 7 48 -28 -48
		mu 0 4 27 28 49 48
		f 4 8 49 -29 -49
		mu 0 4 28 29 50 49
		f 4 9 50 -30 -50
		mu 0 4 29 30 51 50
		f 4 10 51 -31 -51
		mu 0 4 30 31 52 51
		f 4 11 52 -32 -52
		mu 0 4 31 32 53 52
		f 4 12 53 -33 -53
		mu 0 4 32 33 54 53
		f 4 13 54 -34 -54
		mu 0 4 33 34 55 54
		f 4 14 55 -35 -55
		mu 0 4 34 35 56 55
		f 4 15 56 -36 -56
		mu 0 4 35 36 57 56
		f 4 16 57 -37 -57
		mu 0 4 36 37 58 57
		f 4 17 58 -38 -58
		mu 0 4 37 38 59 58
		f 4 18 59 -39 -59
		mu 0 4 38 39 60 59
		f 4 19 40 -40 -60
		mu 0 4 39 40 61 60
		f 20 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 20 0 19 18 17 16 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 20 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
		mu 0 20 80 79 78 77 76 75 74 73 72 71 70 69 68 67 66 65 64 63 62 81;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column" -p "rotunda";
	rename -uid "C2437A9D-4D88-8356-4D55-CB8895EA6991";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
createNode mesh -n "columnShape" -p "column";
	rename -uid "393045FF-40B3-33CC-3771-88946303375A";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_1" -p "rotunda";
	rename -uid "CE5D51EF-4F3C-90C8-82F3-558D1BD63426";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 36 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_1Shape" -p "column_1";
	rename -uid "BB4F0352-4B5B-A187-13B2-208815D6B0D4";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_2" -p "rotunda";
	rename -uid "A7D1CFC5-46C5-66D9-CCF6-C28B258C704B";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 72 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_2Shape" -p "column_2";
	rename -uid "7A1A779C-423E-6B5C-C5BD-9FB7EE261727";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_3" -p "rotunda";
	rename -uid "A79C4B93-4190-86AD-FC52-3D96AF8DF7EC";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 108 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_3Shape" -p "column_3";
	rename -uid "A5667009-44A4-6511-8779-8DB4575F807E";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_4" -p "rotunda";
	rename -uid "0162FF53-4A0B-A815-5D4F-5EB496475CD3";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 144 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_4Shape" -p "column_4";
	rename -uid "8483593A-43CC-B136-CEF4-6CA0DA48DB1E";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_5" -p "rotunda";
	rename -uid "CB97C2E5-48C6-4446-B12D-D78D65E161C1";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 180 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_5Shape" -p "column_5";
	rename -uid "135C9E04-4327-896B-6347-ECA2C63ED8E5";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_6" -p "rotunda";
	rename -uid "17BA6A34-47F9-10D2-DF87-59A636874E41";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 216 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_6Shape" -p "column_6";
	rename -uid "936C91FC-4365-AC66-6941-EAAD09D3832C";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_7" -p "rotunda";
	rename -uid "B2C9BB50-41F2-95A3-ABF8-5EA92063378B";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 252 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_7Shape" -p "column_7";
	rename -uid "8C39340D-42E4-AEB2-CB6B-CDAFE2B60472";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_8" -p "rotunda";
	rename -uid "A9517DD0-4DB8-5F32-7BA2-60B4B2770E86";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 -72.000000000000028 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_8Shape" -p "column_8";
	rename -uid "D13B5693-453B-C4CF-79D1-BA88A3FE0129";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "column_9" -p "rotunda";
	rename -uid "4DB7E2BA-4331-94DF-2B39-33B2421A1E78";
	setAttr ".t" -type "double3" 8.3 5.9 0 ;
	setAttr ".r" -type "double3" 0 -36.000000000000014 0 ;
	setAttr ".s" -type "double3" 1.85 8.4 1.85 ;
	setAttr ".rp" -type "double3" -8.3 -5.9 0 ;
createNode mesh -n "column_9Shape" -p "column_9";
	rename -uid "1D5E7C3B-4B2C-B74D-F77F-65B1EC83DA33";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 10 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "bottom";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "f[80]";
	setAttr ".gtag[1].gtagnm" -type "string" "bottomRing";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0:39]";
	setAttr ".gtag[2].gtagnm" -type "string" "cylBottomCap";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[3].gtagnm" -type "string" "cylBottomRing";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "vtx[0:39]";
	setAttr ".gtag[4].gtagnm" -type "string" "cylSides";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "vtx[0:119]";
	setAttr ".gtag[5].gtagnm" -type "string" "cylTopCap";
	setAttr ".gtag[5].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[6].gtagnm" -type "string" "cylTopRing";
	setAttr ".gtag[6].gtagcmp" -type "componentList" 1 "vtx[80:119]";
	setAttr ".gtag[7].gtagnm" -type "string" "sides";
	setAttr ".gtag[7].gtagcmp" -type "componentList" 1 "f[0:79]";
	setAttr ".gtag[8].gtagnm" -type "string" "top";
	setAttr ".gtag[8].gtagcmp" -type "componentList" 1 "f[81]";
	setAttr ".gtag[9].gtagnm" -type "string" "topRing";
	setAttr ".gtag[9].gtagcmp" -type "componentList" 1 "e[80:119]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 203 ".uvst[0].uvsp[0:202]" -type "float2" 0.9957242 0.10544571
		 0.97740829 0.086372882 0.94738328 0.068251178 0.90638852 0.051526815 0.85543346 0.036611617
		 0.79577255 0.023872823 0.72887522 0.013624132 0.6563884 0.0061178803 0.58009708 0.0015388876
		 0.50187981 -7.4505806e-08 0.42366254 0.0015388876 0.34737122 0.0061178654 0.27488446
		 0.013624117 0.20798701 0.023872808 0.14832622 0.036611587 0.097371072 0.051526785
		 0.056376278 0.068251133 0.026351243 0.086372837 0.008035332 0.10544567 0.0018795133
		 0.12499999 0.008035332 0.14455429 0.026351243 0.16362712 0.056376249 0.18174881 0.097371012
		 0.19847316 0.14832613 0.21338835 0.20798692 0.22612715 0.27488434 0.23637584 0.3473711
		 0.24388209 0.42366236 0.24846107 0.50187963 0.25000003 0.5800969 0.24846107 0.65638816
		 0.24388209 0.72887492 0.23637584 0.79577231 0.22612715 0.85543311 0.21338838 0.90638828
		 0.19847316 0.94738293 0.18174881 0.97740793 0.16362712 0.99572384 0.14455432 1.0018796921
		 0.125 0 0.25 0.025 0.25 0.050000001 0.25 0.075000003 0.25 0.1 0.25 0.125 0.25 0.15000001
		 0.25 0.17500001 0.25 0.20000002 0.25 0.22500002 0.25 0.25000003 0.25 0.27500004 0.25
		 0.30000004 0.25 0.32500005 0.25 0.35000005 0.25 0.37500006 0.25 0.40000007 0.25 0.42500007
		 0.25 0.45000008 0.25 0.47500008 0.25 0.50000006 0.25 0.52500004 0.25 0.55000001 0.25
		 0.57499999 0.25 0.59999996 0.25 0.62499994 0.25 0.64999992 0.25 0.67499989 0.25 0.69999987
		 0.25 0.72499985 0.25 0.74999982 0.25 0.7749998 0.25 0.79999977 0.25 0.82499975 0.25
		 0.84999973 0.25 0.8749997 0.25 0.89999968 0.25 0.92499965 0.25 0.94999963 0.25 0.97499961
		 0.25 0.99999958 0.25 0 0.5 0.025 0.5 0.050000001 0.5 0.075000003 0.5 0.1 0.5 0.125
		 0.5 0.15000001 0.5 0.17500001 0.5 0.20000002 0.5 0.22500002 0.5 0.25000003 0.5 0.27500004
		 0.5 0.30000004 0.5 0.32500005 0.5 0.35000005 0.5 0.37500006 0.5 0.40000007 0.5 0.42500007
		 0.5 0.45000008 0.5 0.47500008 0.5 0.50000006 0.5 0.52500004 0.5 0.55000001 0.5 0.57499999
		 0.5 0.59999996 0.5 0.62499994 0.5 0.64999992 0.5 0.67499989 0.5 0.69999987 0.5 0.72499985
		 0.5 0.74999982 0.5 0.7749998 0.5 0.79999977 0.5 0.82499975 0.5 0.84999973 0.5 0.8749997
		 0.5 0.89999968 0.5 0.92499965 0.5 0.94999963 0.5 0.97499961 0.5 0.99999958 0.5 0
		 0.75 0.025 0.75 0.050000001 0.75 0.075000003 0.75 0.1 0.75 0.125 0.75 0.15000001
		 0.75 0.17500001 0.75 0.20000002 0.75 0.22500002 0.75 0.25000003 0.75 0.27500004 0.75
		 0.30000004 0.75 0.32500005 0.75 0.35000005 0.75 0.37500006 0.75 0.40000007 0.75 0.42500007
		 0.75 0.45000008 0.75 0.47500008 0.75 0.50000006 0.75 0.52500004 0.75 0.55000001 0.75
		 0.57499999 0.75 0.59999996 0.75 0.62499994 0.75 0.64999992 0.75 0.67499989 0.75 0.69999987
		 0.75 0.72499985 0.75 0.74999982 0.75 0.7749998 0.75 0.79999977 0.75 0.82499975 0.75
		 0.84999973 0.75 0.8749997 0.75 0.89999968 0.75 0.92499965 0.75 0.94999963 0.75 0.97499961
		 0.75 0.99999958 0.75 0.9957242 0.85544574 0.97740829 0.83637285 0.94738328 0.81825119
		 0.90638852 0.80152678 0.85543346 0.78661162 0.79577255 0.77387285 0.72887522 0.76362413
		 0.6563884 0.75611788 0.58009708 0.75153887 0.50187981 0.74999994 0.42366254 0.75153887
		 0.34737122 0.75611788 0.27488446 0.76362413 0.20798701 0.77387279 0.14832622 0.78661156
		 0.097371072 0.80152678 0.056376278 0.81825113 0.026351243 0.83637285 0.008035332
		 0.85544568 0.0018795133 0.875 0.008035332 0.89455426 0.026351243 0.91362715 0.056376249
		 0.93174881 0.097371012 0.94847316 0.14832613 0.96338832 0.20798692 0.97612715 0.27488434
		 0.98637581 0.3473711 0.99388206 0.42366236 0.99846107 0.50187963 1 0.5800969 0.99846107
		 0.65638816 0.99388206 0.72887492 0.98637581 0.79577231 0.97612715 0.85543311 0.96338838
		 0.90638828 0.94847316 0.94738293 0.93174881 0.97740793 0.91362715 0.99572384 0.89455432
		 1.0018796921 0.875;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 120 ".vt[0:119]"  0.52347517 -0.5 -0.082910188 0.50406033 -0.5 -0.16377899
		 0.4722338 -0.5 -0.240615 0.42877936 -0.5 -0.31152627 0.37476695 -0.5 -0.37476674
		 0.31152651 -0.5 -0.42877918 0.24061525 -0.5 -0.47223368 0.16377924 -0.5 -0.50406021
		 0.082910441 -0.5 -0.52347511 1.2382866e-07 -0.5 -0.53000033 -0.082910188 -0.5 -0.52347511
		 -0.16377898 -0.5 -0.50406027 -0.24061497 -0.5 -0.47223374 -0.31152624 -0.5 -0.4287793
		 -0.37476668 -0.5 -0.37476686 -0.42877913 -0.5 -0.31152642 -0.47223362 -0.5 -0.24061516
		 -0.50406015 -0.5 -0.16377917 -0.52347499 -0.5 -0.082910389 -0.53000021 -0.5 -8.1509349e-08
		 -0.52347499 -0.5 0.082910217 -0.50406015 -0.5 0.16377899 -0.47223365 -0.5 0.24061497
		 -0.42877918 -0.5 0.31152621 -0.37476677 -0.5 0.37476662 -0.31152633 -0.5 0.42877907
		 -0.2406151 -0.5 0.47223356 -0.16377911 -0.5 0.50406009 -0.082910344 -0.5 0.52347499
		 -4.9918889e-08 -0.5 0.53000015 0.08291024 -0.5 0.52347499 0.16377901 -0.5 0.50406009
		 0.24061498 -0.5 0.47223359 0.31152621 -0.5 0.42877916 0.37476662 -0.5 0.37476668
		 0.42877904 -0.5 0.31152624 0.4722335 -0.5 0.24061501 0.50405997 -0.5 0.16377904 0.52347481 -0.5 0.082910277
		 0.53000003 -0.5 5.3644182e-09 0.65217108 1.1508716e-16 -0.10329356 0.62798309 1.149364e-16 -0.20404388
		 0.58833206 1.1468927e-16 -0.29976994 0.53419441 1.1435184e-16 -0.38811469 0.46690306 1.1393243e-16 -0.46690276
		 0.38811502 1.1344135e-16 -0.53419411 0.2997703 1.1289071e-16 -0.58833188 0.20404424 1.1229407e-16 -0.62798291
		 0.10329392 1.1166611e-16 -0.65217096 1.7625243e-07 1.110223e-16 -0.66030037 -0.10329356 1.103785e-16 -0.65217096
		 -0.20404387 1.0975054e-16 -0.62798297 -0.29976991 1.0915389e-16 -0.58833194 -0.38811466 1.0860326e-16 -0.53419423
		 -0.4669027 1.0811219e-16 -0.46690291 -0.53419405 1.0769277e-16 -0.38811487 -0.58833176 1.0735534e-16 -0.29977015
		 -0.62798285 1.071082e-16 -0.20404409 -0.65217084 1.0695744e-16 -0.10329381 -0.6603002 1.0690677e-16 -7.9567734e-08
		 -0.65217084 1.0695744e-16 0.10329363 -0.62798285 1.071082e-16 0.20404391 -0.58833182 1.0735534e-16 0.29976994
		 -0.53419411 1.0769277e-16 0.38811466 -0.46690279 1.0811219e-16 0.46690267 -0.38811475 1.0860326e-16 0.53419405
		 -0.29977006 1.0915389e-16 0.58833176 -0.20404403 1.0975054e-16 0.6279828 -0.10329375 1.1037849e-16 0.65217084
		 -4.0210782e-08 1.110223e-16 0.6603002 0.10329366 1.1166611e-16 0.65217084 0.20404394 1.1229407e-16 0.6279828
		 0.29976997 1.1289071e-16 0.58833182 0.38811466 1.1344135e-16 0.53419411 0.46690267 1.1393242e-16 0.46690273
		 0.53419399 1.1435184e-16 0.38811469 0.5883317 1.1468927e-16 0.29977 0.62798268 1.149364e-16 0.20404397
		 0.65217066 1.1508716e-16 0.10329372 0.66030002 1.1513784e-16 2.8663873e-08 0.39507559 0.5 -0.062573746
		 0.38042286 0.5 -0.12360681 0.35640284 0.5 -0.18159625 0.32360706 0.5 -0.23511419
		 0.28284296 0.5 -0.28284284 0.23511432 0.5 -0.32360697 0.1815964 0.5 -0.35640278 0.12360695 0.5 -0.38042283
		 0.062573895 0.5 -0.39507559 7.1525577e-08 0.5 -0.40000024 -0.062573746 0.5 -0.39507559
		 -0.12360679 0.5 -0.38042286 -0.18159622 0.5 -0.35640284 -0.23511416 0.5 -0.32360703
		 -0.28284279 0.5 -0.28284293 -0.32360691 0.5 -0.23511431 -0.35640275 0.5 -0.18159637
		 -0.38042277 0.5 -0.12360694 -0.3950755 0.5 -0.062573895 -0.40000015 0.5 -8.3446501e-08
		 -0.3950755 0.5 0.062573723 -0.38042277 0.5 0.12360676 -0.35640278 0.5 0.18159617
		 -0.32360697 0.5 0.2351141 -0.28284287 0.5 0.28284273 -0.23511423 0.5 0.32360682 -0.18159632 0.5 0.35640267
		 -0.12360691 0.5 0.38042268 -0.062573865 0.5 0.39507541 -5.9604645e-08 0.5 0.40000007
		 0.062573746 0.5 0.39507541 0.12360677 0.5 0.38042268 0.18159619 0.5 0.3564027 0.2351141 0.5 0.32360688
		 0.28284273 0.5 0.28284276 0.32360682 0.5 0.23511413 0.35640261 0.5 0.18159622 0.38042259 0.5 0.12360679
		 0.39507532 0.5 0.062573776 0.39999998 0.5 -1.7881394e-08;
	setAttr -s 200 ".ed";
	setAttr ".ed[0:165]"  0 1 0 1 2 0 2 3 0 3 4 0 4 5 0 5 6 0 6 7 0 7 8 0 8 9 0
		 9 10 0 10 11 0 11 12 0 12 13 0 13 14 0 14 15 0 15 16 0 16 17 0 17 18 0 18 19 0 19 20 0
		 20 21 0 21 22 0 22 23 0 23 24 0 24 25 0 25 26 0 26 27 0 27 28 0 28 29 0 29 30 0 30 31 0
		 31 32 0 32 33 0 33 34 0 34 35 0 35 36 0 36 37 0 37 38 0 38 39 0 39 0 0 40 41 1 41 42 1
		 42 43 1 43 44 1 44 45 1 45 46 1 46 47 1 47 48 1 48 49 1 49 50 1 50 51 1 51 52 1 52 53 1
		 53 54 1 54 55 1 55 56 1 56 57 1 57 58 1 58 59 1 59 60 1 60 61 1 61 62 1 62 63 1 63 64 1
		 64 65 1 65 66 1 66 67 1 67 68 1 68 69 1 69 70 1 70 71 1 71 72 1 72 73 1 73 74 1 74 75 1
		 75 76 1 76 77 1 77 78 1 78 79 1 79 40 1 80 81 0 81 82 0 82 83 0 83 84 0 84 85 0 85 86 0
		 86 87 0 87 88 0 88 89 0 89 90 0 90 91 0 91 92 0 92 93 0 93 94 0 94 95 0 95 96 0 96 97 0
		 97 98 0 98 99 0 99 100 0 100 101 0 101 102 0 102 103 0 103 104 0 104 105 0 105 106 0
		 106 107 0 107 108 0 108 109 0 109 110 0 110 111 0 111 112 0 112 113 0 113 114 0 114 115 0
		 115 116 0 116 117 0 117 118 0 118 119 0 119 80 0 0 40 1 1 41 1 2 42 1 3 43 1 4 44 1
		 5 45 1 6 46 1 7 47 1 8 48 1 9 49 1 10 50 1 11 51 1 12 52 1 13 53 1 14 54 1 15 55 1
		 16 56 1 17 57 1 18 58 1 19 59 1 20 60 1 21 61 1 22 62 1 23 63 1 24 64 1 25 65 1 26 66 1
		 27 67 1 28 68 1 29 69 1 30 70 1 31 71 1 32 72 1 33 73 1 34 74 1 35 75 1 36 76 1 37 77 1
		 38 78 1 39 79 1 40 80 1 41 81 1 42 82 1 43 83 1 44 84 1 45 85 1;
	setAttr ".ed[166:199]" 46 86 1 47 87 1 48 88 1 49 89 1 50 90 1 51 91 1 52 92 1
		 53 93 1 54 94 1 55 95 1 56 96 1 57 97 1 58 98 1 59 99 1 60 100 1 61 101 1 62 102 1
		 63 103 1 64 104 1 65 105 1 66 106 1 67 107 1 68 108 1 69 109 1 70 110 1 71 111 1
		 72 112 1 73 113 1 74 114 1 75 115 1 76 116 1 77 117 1 78 118 1 79 119 1;
	setAttr -s 82 -ch 400 ".fc[0:81]" -type "polyFaces" 
		f 4 0 121 -41 -121
		mu 0 4 40 41 82 81
		f 4 1 122 -42 -122
		mu 0 4 41 42 83 82
		f 4 2 123 -43 -123
		mu 0 4 42 43 84 83
		f 4 3 124 -44 -124
		mu 0 4 43 44 85 84
		f 4 4 125 -45 -125
		mu 0 4 44 45 86 85
		f 4 5 126 -46 -126
		mu 0 4 45 46 87 86
		f 4 6 127 -47 -127
		mu 0 4 46 47 88 87
		f 4 7 128 -48 -128
		mu 0 4 47 48 89 88
		f 4 8 129 -49 -129
		mu 0 4 48 49 90 89
		f 4 9 130 -50 -130
		mu 0 4 49 50 91 90
		f 4 10 131 -51 -131
		mu 0 4 50 51 92 91
		f 4 11 132 -52 -132
		mu 0 4 51 52 93 92
		f 4 12 133 -53 -133
		mu 0 4 52 53 94 93
		f 4 13 134 -54 -134
		mu 0 4 53 54 95 94
		f 4 14 135 -55 -135
		mu 0 4 54 55 96 95
		f 4 15 136 -56 -136
		mu 0 4 55 56 97 96
		f 4 16 137 -57 -137
		mu 0 4 56 57 98 97
		f 4 17 138 -58 -138
		mu 0 4 57 58 99 98
		f 4 18 139 -59 -139
		mu 0 4 58 59 100 99
		f 4 19 140 -60 -140
		mu 0 4 59 60 101 100
		f 4 20 141 -61 -141
		mu 0 4 60 61 102 101
		f 4 21 142 -62 -142
		mu 0 4 61 62 103 102
		f 4 22 143 -63 -143
		mu 0 4 62 63 104 103
		f 4 23 144 -64 -144
		mu 0 4 63 64 105 104
		f 4 24 145 -65 -145
		mu 0 4 64 65 106 105
		f 4 25 146 -66 -146
		mu 0 4 65 66 107 106
		f 4 26 147 -67 -147
		mu 0 4 66 67 108 107
		f 4 27 148 -68 -148
		mu 0 4 67 68 109 108
		f 4 28 149 -69 -149
		mu 0 4 68 69 110 109
		f 4 29 150 -70 -150
		mu 0 4 69 70 111 110
		f 4 30 151 -71 -151
		mu 0 4 70 71 112 111
		f 4 31 152 -72 -152
		mu 0 4 71 72 113 112
		f 4 32 153 -73 -153
		mu 0 4 72 73 114 113
		f 4 33 154 -74 -154
		mu 0 4 73 74 115 114
		f 4 34 155 -75 -155
		mu 0 4 74 75 116 115
		f 4 35 156 -76 -156
		mu 0 4 75 76 117 116
		f 4 36 157 -77 -157
		mu 0 4 76 77 118 117
		f 4 37 158 -78 -158
		mu 0 4 77 78 119 118
		f 4 38 159 -79 -159
		mu 0 4 78 79 120 119
		f 4 39 120 -80 -160
		mu 0 4 79 80 121 120
		f 4 40 161 -81 -161
		mu 0 4 81 82 123 122
		f 4 41 162 -82 -162
		mu 0 4 82 83 124 123
		f 4 42 163 -83 -163
		mu 0 4 83 84 125 124
		f 4 43 164 -84 -164
		mu 0 4 84 85 126 125
		f 4 44 165 -85 -165
		mu 0 4 85 86 127 126
		f 4 45 166 -86 -166
		mu 0 4 86 87 128 127
		f 4 46 167 -87 -167
		mu 0 4 87 88 129 128
		f 4 47 168 -88 -168
		mu 0 4 88 89 130 129
		f 4 48 169 -89 -169
		mu 0 4 89 90 131 130
		f 4 49 170 -90 -170
		mu 0 4 90 91 132 131
		f 4 50 171 -91 -171
		mu 0 4 91 92 133 132
		f 4 51 172 -92 -172
		mu 0 4 92 93 134 133
		f 4 52 173 -93 -173
		mu 0 4 93 94 135 134
		f 4 53 174 -94 -174
		mu 0 4 94 95 136 135
		f 4 54 175 -95 -175
		mu 0 4 95 96 137 136
		f 4 55 176 -96 -176
		mu 0 4 96 97 138 137
		f 4 56 177 -97 -177
		mu 0 4 97 98 139 138
		f 4 57 178 -98 -178
		mu 0 4 98 99 140 139
		f 4 58 179 -99 -179
		mu 0 4 99 100 141 140
		f 4 59 180 -100 -180
		mu 0 4 100 101 142 141
		f 4 60 181 -101 -181
		mu 0 4 101 102 143 142
		f 4 61 182 -102 -182
		mu 0 4 102 103 144 143
		f 4 62 183 -103 -183
		mu 0 4 103 104 145 144
		f 4 63 184 -104 -184
		mu 0 4 104 105 146 145
		f 4 64 185 -105 -185
		mu 0 4 105 106 147 146
		f 4 65 186 -106 -186
		mu 0 4 106 107 148 147
		f 4 66 187 -107 -187
		mu 0 4 107 108 149 148
		f 4 67 188 -108 -188
		mu 0 4 108 109 150 149
		f 4 68 189 -109 -189
		mu 0 4 109 110 151 150
		f 4 69 190 -110 -190
		mu 0 4 110 111 152 151
		f 4 70 191 -111 -191
		mu 0 4 111 112 153 152
		f 4 71 192 -112 -192
		mu 0 4 112 113 154 153
		f 4 72 193 -113 -193
		mu 0 4 113 114 155 154
		f 4 73 194 -114 -194
		mu 0 4 114 115 156 155
		f 4 74 195 -115 -195
		mu 0 4 115 116 157 156
		f 4 75 196 -116 -196
		mu 0 4 116 117 158 157
		f 4 76 197 -117 -197
		mu 0 4 117 118 159 158
		f 4 77 198 -118 -198
		mu 0 4 118 119 160 159
		f 4 78 199 -119 -199
		mu 0 4 119 120 161 160
		f 4 79 160 -120 -200
		mu 0 4 120 121 162 161
		f 40 -40 -39 -38 -37 -36 -35 -34 -33 -32 -31 -30 -29 -28 -27 -26 -25 -24 -23 -22 -21
		 -20 -19 -18 -17 -16 -15 -14 -13 -12 -11 -10 -9 -8 -7 -6 -5 -4 -3 -2 -1
		mu 0 40 0 39 38 37 36 35 34 33 32 31 30 29 28 27 26 25 24 23 22 21 20 19 18 17 16 15 14
		 13 12 11 10 9 8 7 6 5 4 3 2 1
		f 40 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 100 101 102 103 104
		 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119
		mu 0 40 201 200 199 198 197 196 195 194 193 192 191 190 189 188 187 186 185 184 183 182
		 181 180 179 178 177 176 175 174 173 172 171 170 169 168 167 166 165 164 163 202;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "studio";
	rename -uid "283FC507-4959-1B99-4A37-948C275AAFC4";
	setAttr ".rp" -type "double3" 0 150 0 ;
	setAttr ".sp" -type "double3" 0 150 0 ;
createNode transform -n "ground" -p "studio";
	rename -uid "4713AD56-4B20-E320-CF87-3FAD77C47E25";
	setAttr ".s" -type "double3" 700 1 700 ;
createNode mesh -n "groundShape" -p "ground";
	rename -uid "5EC914BA-4A14-2027-6BF8-21BF7A6D4D5F";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 5 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "back";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "e[3]";
	setAttr ".gtag[1].gtagnm" -type "string" "front";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0]";
	setAttr ".gtag[2].gtagnm" -type "string" "left";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "e[1]";
	setAttr ".gtag[3].gtagnm" -type "string" "right";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "e[2]";
	setAttr ".gtag[4].gtagnm" -type "string" "rim";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "e[0:3]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 4 ".uvst[0].uvsp[0:3]" -type "float2" 0 0 1 0 0 1 1 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 4 ".vt[0:3]"  -0.5 0 0.5 0.5 0 0.5 -0.5 0 -0.5 0.5 0 -0.5;
	setAttr -s 4 ".ed[0:3]"  0 1 0 0 2 0 1 3 0 2 3 0;
	setAttr -ch 4 ".fc[0]" -type "polyFaces" 
		f 4 0 2 -4 -2
		mu 0 4 0 1 3 2;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "wallBack" -p "studio";
	rename -uid "D20693E8-41A6-2E43-D682-1481FADDCB40";
	setAttr ".t" -type "double3" 0 150 -190 ;
	setAttr ".r" -type "double3" 90 0 0 ;
	setAttr ".s" -type "double3" 800 1 460 ;
createNode mesh -n "wallBackShape" -p "wallBack";
	rename -uid "5183ACAA-420A-4B2E-CE8C-E0BA4556DA10";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 5 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "back";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "e[3]";
	setAttr ".gtag[1].gtagnm" -type "string" "front";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0]";
	setAttr ".gtag[2].gtagnm" -type "string" "left";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "e[1]";
	setAttr ".gtag[3].gtagnm" -type "string" "right";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "e[2]";
	setAttr ".gtag[4].gtagnm" -type "string" "rim";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "e[0:3]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 4 ".uvst[0].uvsp[0:3]" -type "float2" 0 0 1 0 0 1 1 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 4 ".vt[0:3]"  -0.5 0 0.5 0.5 0 0.5 -0.5 0 -0.5 0.5 0 -0.5;
	setAttr -s 4 ".ed[0:3]"  0 1 0 0 2 0 1 3 0 2 3 0;
	setAttr -ch 4 ".fc[0]" -type "polyFaces" 
		f 4 0 2 -4 -2
		mu 0 4 0 1 3 2;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "wallFront" -p "studio";
	rename -uid "7E64E330-4DD8-8503-9BAE-8C9F26F08AB3";
	setAttr ".t" -type "double3" 0 150 190 ;
	setAttr ".r" -type "double3" 90 0 0 ;
	setAttr ".s" -type "double3" 800 1 460 ;
createNode mesh -n "wallFrontShape" -p "wallFront";
	rename -uid "44D493A5-4EBF-3DD9-C1D6-48ABAC11E976";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 5 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "back";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "e[3]";
	setAttr ".gtag[1].gtagnm" -type "string" "front";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0]";
	setAttr ".gtag[2].gtagnm" -type "string" "left";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "e[1]";
	setAttr ".gtag[3].gtagnm" -type "string" "right";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "e[2]";
	setAttr ".gtag[4].gtagnm" -type "string" "rim";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "e[0:3]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 4 ".uvst[0].uvsp[0:3]" -type "float2" 0 0 1 0 0 1 1 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 4 ".vt[0:3]"  -0.5 0 0.5 0.5 0 0.5 -0.5 0 -0.5 0.5 0 -0.5;
	setAttr -s 4 ".ed[0:3]"  0 1 0 0 2 0 1 3 0 2 3 0;
	setAttr -ch 4 ".fc[0]" -type "polyFaces" 
		f 4 0 2 -4 -2
		mu 0 4 0 1 3 2;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "wallLeft" -p "studio";
	rename -uid "2A812A2A-43A8-A687-B1E9-21BB56C9FDC6";
	setAttr ".t" -type "double3" -190 150 0 ;
	setAttr ".r" -type "double3" 90 0 90 ;
	setAttr ".s" -type "double3" 800 1 460 ;
createNode mesh -n "wallLeftShape" -p "wallLeft";
	rename -uid "9B633A0F-441B-5AF1-2576-C79E24A0ACC2";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 5 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "back";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "e[3]";
	setAttr ".gtag[1].gtagnm" -type "string" "front";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0]";
	setAttr ".gtag[2].gtagnm" -type "string" "left";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "e[1]";
	setAttr ".gtag[3].gtagnm" -type "string" "right";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "e[2]";
	setAttr ".gtag[4].gtagnm" -type "string" "rim";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "e[0:3]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 4 ".uvst[0].uvsp[0:3]" -type "float2" 0 0 1 0 0 1 1 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 4 ".vt[0:3]"  -0.5 0 0.5 0.5 0 0.5 -0.5 0 -0.5 0.5 0 -0.5;
	setAttr -s 4 ".ed[0:3]"  0 1 0 0 2 0 1 3 0 2 3 0;
	setAttr -ch 4 ".fc[0]" -type "polyFaces" 
		f 4 0 2 -4 -2
		mu 0 4 0 1 3 2;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode transform -n "wallRight" -p "studio";
	rename -uid "5FDACB93-4E55-95B5-532E-BEB67CC308AB";
	setAttr ".t" -type "double3" 190 150 0 ;
	setAttr ".r" -type "double3" 90 0 90 ;
	setAttr ".s" -type "double3" 800 1 460 ;
createNode mesh -n "wallRightShape" -p "wallRight";
	rename -uid "E45DA9AB-467A-F99D-206F-DAAACF6261BA";
	setAttr -k off ".v";
	setAttr ".vir" yes;
	setAttr ".vif" yes;
	setAttr -s 5 ".gtag";
	setAttr ".gtag[0].gtagnm" -type "string" "back";
	setAttr ".gtag[0].gtagcmp" -type "componentList" 1 "e[3]";
	setAttr ".gtag[1].gtagnm" -type "string" "front";
	setAttr ".gtag[1].gtagcmp" -type "componentList" 1 "e[0]";
	setAttr ".gtag[2].gtagnm" -type "string" "left";
	setAttr ".gtag[2].gtagcmp" -type "componentList" 1 "e[1]";
	setAttr ".gtag[3].gtagnm" -type "string" "right";
	setAttr ".gtag[3].gtagcmp" -type "componentList" 1 "e[2]";
	setAttr ".gtag[4].gtagnm" -type "string" "rim";
	setAttr ".gtag[4].gtagcmp" -type "componentList" 1 "e[0:3]";
	setAttr ".uvst[0].uvsn" -type "string" "map1";
	setAttr -s 4 ".uvst[0].uvsp[0:3]" -type "float2" 0 0 1 0 0 1 1 1;
	setAttr ".cuvs" -type "string" "map1";
	setAttr ".dcc" -type "string" "Ambient+Diffuse";
	setAttr ".covm[0]"  0 1 1;
	setAttr ".cdvm[0]"  0 1 1;
	setAttr -s 4 ".vt[0:3]"  -0.5 0 0.5 0.5 0 0.5 -0.5 0 -0.5 0.5 0 -0.5;
	setAttr -s 4 ".ed[0:3]"  0 1 0 0 2 0 1 3 0 2 3 0;
	setAttr -ch 4 ".fc[0]" -type "polyFaces" 
		f 4 0 2 -4 -2
		mu 0 4 0 1 3 2;
	setAttr ".cd" -type "dataPolyComponent" Index_Data Edge 0 ;
	setAttr ".cvd" -type "dataPolyComponent" Index_Data Vertex 0 ;
	setAttr ".pd[0]" -type "dataPolyComponent" Index_Data UV 0 ;
	setAttr ".hfd" -type "dataPolyComponent" Index_Data Face 0 ;
createNode lightLinker -s -n "lightLinker1";
	rename -uid "76B7B602-4AED-3712-10F7-69981F1A86F7";
	setAttr -s 11 ".lnk";
	setAttr -s 11 ".slnk";
createNode UsdDefaultSettings -n "UsdDefaultRenderSettings";
	rename -uid "5101BC44-43A2-6685-774C-AEBB29C02A4B";
	setAttr ".srl" -type "string" "#usda 1.0\n(\n    renderSettingsPrimPath = \"/Render/SceneRenderSettings\"\n)\n\ndef Scope \"Render\"\n{\n    def RenderSettings \"SceneRenderSettings\"\n    {\n        custom string adskUsd:externalCamera = \"|persp\" (\n            displayName = \"External Camera\"\n        )\n        rel products = </Render/BeautyProduct>\n    }\n\n    def RenderVar \"color\"\n    {\n        uniform string sourceName = \"color\"\n    }\n\n    def RenderProduct \"BeautyProduct\"\n    {\n        rel orderedVars = </Render/color>\n        token productName = \"./default.png\"\n    }\n}\n\n";
	setAttr ".ssl" -type "string" "#usda 1.0\n\n";
	setAttr ".asp" -type "string" "UsdDefaultRenderSettings,/Render/SceneRenderSettings";
lockNode -l 1 ;
createNode shapeEditorManager -n "shapeEditorManager";
	rename -uid "E808B2AA-4925-1E41-5A3A-0DB743C6908D";
createNode poseInterpolatorManager -n "poseInterpolatorManager";
	rename -uid "D35AFFE2-4ACF-14D1-024B-8FA6D20E4172";
createNode displayLayerManager -n "layerManager";
	rename -uid "97B73190-4D16-2C86-A4F6-1AB391F8EF64";
createNode displayLayer -n "defaultLayer";
	rename -uid "211728D2-47A0-62E8-B494-FABFE01214BA";
	setAttr ".ufem" -type "stringArray" 0  ;
createNode renderLayerManager -n "renderLayerManager";
	rename -uid "D7C52064-4018-E757-DDCE-28B131D8EF48";
createNode renderLayer -n "defaultRenderLayer";
	rename -uid "992A8479-4B80-A405-9546-AF9EA4356B75";
	setAttr ".g" yes;
createNode lambert -n "ground_mat";
	rename -uid "31389424-4569-AF80-F1E5-B3956E494E2B";
	setAttr ".c" -type "float3" 0.17 0.17 0.19 ;
createNode shadingEngine -n "ground_matSG";
	rename -uid "589F2426-41D9-EAE4-F095-B287060B7F85";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo1";
	rename -uid "E2D53AE5-493C-C4C9-D829-8795260D6056";
createNode lambert -n "wallBack_mat";
	rename -uid "6C9CD407-4F52-1A2A-660C-60A4003B59AC";
	setAttr ".c" -type "float3" 0.36000001 0.37 0.40000001 ;
createNode shadingEngine -n "wallBack_matSG";
	rename -uid "03AD116D-49CB-82BB-938F-66BE4D617606";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo2";
	rename -uid "5DF45210-451C-8785-51C9-3DAA1DC3D659";
createNode lambert -n "wallFront_mat";
	rename -uid "49EBFCEE-4FAF-1558-2F4E-D99B00E1823A";
	setAttr ".c" -type "float3" 0.36000001 0.37 0.40000001 ;
createNode shadingEngine -n "wallFront_matSG";
	rename -uid "9FCD5199-4D7E-8296-25EB-E8BDAF3BB5C2";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo3";
	rename -uid "829EFE8E-4060-6E65-1BED-0F8EB107030F";
createNode lambert -n "wallLeft_mat";
	rename -uid "21A7676A-46D3-42C7-2EF0-DCA78D883776";
	setAttr ".c" -type "float3" 0.33000001 0.34 0.37 ;
createNode shadingEngine -n "wallLeft_matSG";
	rename -uid "B678D041-443C-17D2-1F70-F19044F69C43";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo4";
	rename -uid "33A1A791-4905-AF84-A76F-EF9D614DED70";
createNode lambert -n "wallRight_mat";
	rename -uid "B3B92B4B-4735-AFD2-7DF9-77B2954C6E4A";
	setAttr ".c" -type "float3" 0.33000001 0.34 0.37 ;
createNode shadingEngine -n "wallRight_matSG";
	rename -uid "1409634A-4C82-8383-8684-5B881CA44162";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo5";
	rename -uid "DF28BB93-4AC4-B86C-213A-F8943FF336DC";
createNode standardSurface -n "limestone_mat";
	rename -uid "34116FD9-47DF-EC24-53EE-75BFD76F13D7";
	setAttr ".bc" -type "float3" 0.74000001 0.70999998 0.63999999 ;
	setAttr ".s" 0.30000001192092896;
	setAttr ".sr" 0.75999999046325684;
createNode shadingEngine -n "limestone_matSG";
	rename -uid "7590D242-4778-8B61-5895-9D82CAF4747F";
	setAttr ".ihi" 0;
	setAttr -s 16 ".dsm";
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo6";
	rename -uid "A317BB0A-4329-DDD8-A915-6AA8CE66B194";
createNode standardSurface -n "bronze_mat";
	rename -uid "1785071D-4211-ECCD-DD45-D19D9E0F9BF3";
	setAttr ".bc" -type "float3" 0.60000002 0.41 0.18000001 ;
	setAttr ".sr" 0.34000000357627869;
	setAttr ".m" 0.69999998807907104;
createNode shadingEngine -n "bronze_matSG";
	rename -uid "BF161ADB-4A92-7A55-0D07-379F24A62F6A";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo7";
	rename -uid "E6EAF34B-4CFD-8A4F-D70C-9C99BCF65DBD";
createNode standardSurface -n "shadowStone_mat";
	rename -uid "F5EC88F6-46B6-A35D-2CDA-FA904069A34B";
	setAttr ".bc" -type "float3" 0.25999999 0.25 0.23999999 ;
	setAttr ".s" 0.25;
	setAttr ".sr" 0.81999999284744263;
createNode shadingEngine -n "shadowStone_matSG";
	rename -uid "FE9C5B08-48CB-72A4-9704-AD8782112110";
	setAttr ".ihi" 0;
	setAttr -s 4 ".dsm";
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo8";
	rename -uid "9FC39141-4205-B36F-0F00-03A08C8AA526";
createNode standardSurface -n "glow_mat";
	rename -uid "4018AD8B-49B8-DFCC-53C5-6E907EED87F2";
	setAttr ".bc" -type "float3" 0.44999999 0.30000001 0.029999999 ;
	setAttr ".sr" 0.05000000074505806;
	setAttr ".sior" 1.5499999523162842;
	setAttr ".t" 0.55000001192092896;
	setAttr ".trc" -type "float3" 0.94999999 0.77999997 0.38 ;
	setAttr ".e" 1.5;
	setAttr ".ec" -type "float3" 1 0.62 0.18000001 ;
createNode shadingEngine -n "glow_matSG";
	rename -uid "AAB516B8-4806-0B6C-B743-18ACAD94EDC2";
	setAttr ".ihi" 0;
	setAttr ".ro" yes;
createNode materialInfo -n "materialInfo9";
	rename -uid "8769FE65-42EC-E028-7365-52AA29C3837F";
createNode script -n "uiConfigurationScriptNode";
	rename -uid "19D2BF62-4916-5601-F7BB-74B8D0CEA1C1";
	setAttr ".b" -type "string" (
		"// Maya Mel UI Configuration File.\n//\n//  This script is machine generated.  Edit at your own risk.\n//\n//\n\nglobal string $gMainPane;\nif (`paneLayout -exists $gMainPane`) {\n\n\tglobal int $gUseScenePanelConfig;\n\tint    $useSceneConfig = $gUseScenePanelConfig;\n\tint    $nodeEditorPanelVisible = stringArrayContains(\"nodeEditorPanel1\", `getPanel -vis`);\n\tint    $nodeEditorWorkspaceControlOpen = (`workspaceControl -exists nodeEditorPanel1Window` && `workspaceControl -q -visible nodeEditorPanel1Window`);\n\tint    $menusOkayInPanels = `optionVar -q allowMenusInPanels`;\n\tint    $nVisPanes = `paneLayout -q -nvp $gMainPane`;\n\tint    $nPanes = 0;\n\tstring $editorName;\n\tstring $panelName;\n\tstring $itemFilterName;\n\tstring $panelConfig;\n\n\t//\n\t//  get current state of the UI\n\t//\n\tsceneUIReplacement -update $gMainPane;\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"modelPanel\" (localizedPanelLabel(\"Top View\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tmodelPanel -edit -l (localizedPanelLabel(\"Top View\")) -mbv $menusOkayInPanels  $panelName;\n"
		+ "\t\t$editorName = $panelName;\n        modelEditor -e \n            -camera \"|top\" \n            -useInteractiveMode 0\n            -displayLights \"default\" \n            -displayAppearance \"smoothShaded\" \n            -activeOnly 0\n            -ignorePanZoom 0\n            -wireframeOnShaded 0\n            -headsUpDisplay 1\n            -holdOuts 1\n            -selectionHiliteDisplay 1\n            -useDefaultMaterial 0\n            -bufferMode \"double\" \n            -twoSidedLighting 0\n            -backfaceCulling 0\n            -xray 0\n            -jointXray 0\n            -activeComponentsXray 0\n            -displayTextures 0\n            -smoothWireframe 0\n            -lineWidth 1\n            -textureAnisotropic 0\n            -textureHilight 1\n            -textureSampling 2\n            -textureDisplay \"modulate\" \n            -textureMaxSize 32768\n            -fogging 0\n            -fogSource \"fragment\" \n            -fogMode \"linear\" \n            -fogStart 0\n            -fogEnd 100\n            -fogDensity 0.1\n            -fogColor 0.5 0.5 0.5 1 \n"
		+ "            -depthOfFieldPreview 1\n            -maxConstantTransparency 1\n            -rendererName \"vp2Renderer\" \n            -objectFilterShowInHUD 1\n            -isFiltered 0\n            -colorResolution 256 256 \n            -bumpResolution 512 512 \n            -textureCompression 0\n            -transparencyAlgorithm \"frontAndBackCull\" \n            -transpInShadows 0\n            -cullingOverride \"none\" \n            -lowQualityLighting 0\n            -maximumNumHardwareLights 1\n            -occlusionCulling 0\n            -shadingModel 0\n            -useBaseRenderer 0\n            -useReducedRenderer 0\n            -smallObjectCulling 0\n            -smallObjectThreshold -1 \n            -interactiveDisableShadows 0\n            -interactiveBackFaceCull 0\n            -sortTransparent 1\n            -controllers 1\n            -nurbsCurves 1\n            -nurbsSurfaces 1\n            -polymeshes 1\n            -subdivSurfaces 1\n            -planes 1\n            -lights 1\n            -cameras 1\n            -controlVertices 1\n"
		+ "            -hulls 1\n            -grid 1\n            -imagePlane 1\n            -joints 1\n            -ikHandles 1\n            -deformers 1\n            -dynamics 1\n            -particleInstancers 1\n            -fluids 1\n            -hairSystems 1\n            -follicles 1\n            -nCloths 1\n            -nParticles 1\n            -nRigids 1\n            -dynamicConstraints 1\n            -locators 1\n            -manipulators 1\n            -pluginShapes 1\n            -dimensions 1\n            -handles 1\n            -pivots 1\n            -textures 1\n            -strokes 1\n            -motionTrails 1\n            -clipGhosts 1\n            -bluePencil 1\n            -greasePencils 0\n            -excludeObjectPreset \"All\" \n            -shadows 0\n            -captureSequenceNumber -1\n            -width 1\n            -height 1\n            -sceneRenderFilter 0\n            $editorName;\n        modelEditor -e -viewSelected 0 $editorName;\n        modelEditor -e \n            -pluginObjects \"gpuCacheDisplayFilter\" 1 \n            -pluginObjects \"mayaUsdProxyShapeBaseDisplayFilter\" 1 \n"
		+ "            $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"modelPanel\" (localizedPanelLabel(\"Side View\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tmodelPanel -edit -l (localizedPanelLabel(\"Side View\")) -mbv $menusOkayInPanels  $panelName;\n\t\t$editorName = $panelName;\n        modelEditor -e \n            -camera \"|side\" \n            -useInteractiveMode 0\n            -displayLights \"default\" \n            -displayAppearance \"smoothShaded\" \n            -activeOnly 0\n            -ignorePanZoom 0\n            -wireframeOnShaded 0\n            -headsUpDisplay 1\n            -holdOuts 1\n            -selectionHiliteDisplay 1\n            -useDefaultMaterial 0\n            -bufferMode \"double\" \n            -twoSidedLighting 0\n            -backfaceCulling 0\n            -xray 0\n            -jointXray 0\n            -activeComponentsXray 0\n            -displayTextures 0\n            -smoothWireframe 0\n            -lineWidth 1\n"
		+ "            -textureAnisotropic 0\n            -textureHilight 1\n            -textureSampling 2\n            -textureDisplay \"modulate\" \n            -textureMaxSize 32768\n            -fogging 0\n            -fogSource \"fragment\" \n            -fogMode \"linear\" \n            -fogStart 0\n            -fogEnd 100\n            -fogDensity 0.1\n            -fogColor 0.5 0.5 0.5 1 \n            -depthOfFieldPreview 1\n            -maxConstantTransparency 1\n            -rendererName \"vp2Renderer\" \n            -objectFilterShowInHUD 1\n            -isFiltered 0\n            -colorResolution 256 256 \n            -bumpResolution 512 512 \n            -textureCompression 0\n            -transparencyAlgorithm \"frontAndBackCull\" \n            -transpInShadows 0\n            -cullingOverride \"none\" \n            -lowQualityLighting 0\n            -maximumNumHardwareLights 1\n            -occlusionCulling 0\n            -shadingModel 0\n            -useBaseRenderer 0\n            -useReducedRenderer 0\n            -smallObjectCulling 0\n            -smallObjectThreshold -1 \n"
		+ "            -interactiveDisableShadows 0\n            -interactiveBackFaceCull 0\n            -sortTransparent 1\n            -controllers 1\n            -nurbsCurves 1\n            -nurbsSurfaces 1\n            -polymeshes 1\n            -subdivSurfaces 1\n            -planes 1\n            -lights 1\n            -cameras 1\n            -controlVertices 1\n            -hulls 1\n            -grid 1\n            -imagePlane 1\n            -joints 1\n            -ikHandles 1\n            -deformers 1\n            -dynamics 1\n            -particleInstancers 1\n            -fluids 1\n            -hairSystems 1\n            -follicles 1\n            -nCloths 1\n            -nParticles 1\n            -nRigids 1\n            -dynamicConstraints 1\n            -locators 1\n            -manipulators 1\n            -pluginShapes 1\n            -dimensions 1\n            -handles 1\n            -pivots 1\n            -textures 1\n            -strokes 1\n            -motionTrails 1\n            -clipGhosts 1\n            -bluePencil 1\n            -greasePencils 0\n"
		+ "            -excludeObjectPreset \"All\" \n            -shadows 0\n            -captureSequenceNumber -1\n            -width 1\n            -height 1\n            -sceneRenderFilter 0\n            $editorName;\n        modelEditor -e -viewSelected 0 $editorName;\n        modelEditor -e \n            -pluginObjects \"gpuCacheDisplayFilter\" 1 \n            -pluginObjects \"mayaUsdProxyShapeBaseDisplayFilter\" 1 \n            $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"modelPanel\" (localizedPanelLabel(\"Front View\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tmodelPanel -edit -l (localizedPanelLabel(\"Front View\")) -mbv $menusOkayInPanels  $panelName;\n\t\t$editorName = $panelName;\n        modelEditor -e \n            -camera \"|front\" \n            -useInteractiveMode 0\n            -displayLights \"default\" \n            -displayAppearance \"smoothShaded\" \n            -activeOnly 0\n            -ignorePanZoom 0\n            -wireframeOnShaded 0\n"
		+ "            -headsUpDisplay 1\n            -holdOuts 1\n            -selectionHiliteDisplay 1\n            -useDefaultMaterial 0\n            -bufferMode \"double\" \n            -twoSidedLighting 0\n            -backfaceCulling 0\n            -xray 0\n            -jointXray 0\n            -activeComponentsXray 0\n            -displayTextures 0\n            -smoothWireframe 0\n            -lineWidth 1\n            -textureAnisotropic 0\n            -textureHilight 1\n            -textureSampling 2\n            -textureDisplay \"modulate\" \n            -textureMaxSize 32768\n            -fogging 0\n            -fogSource \"fragment\" \n            -fogMode \"linear\" \n            -fogStart 0\n            -fogEnd 100\n            -fogDensity 0.1\n            -fogColor 0.5 0.5 0.5 1 \n            -depthOfFieldPreview 1\n            -maxConstantTransparency 1\n            -rendererName \"vp2Renderer\" \n            -objectFilterShowInHUD 1\n            -isFiltered 0\n            -colorResolution 256 256 \n            -bumpResolution 512 512 \n            -textureCompression 0\n"
		+ "            -transparencyAlgorithm \"frontAndBackCull\" \n            -transpInShadows 0\n            -cullingOverride \"none\" \n            -lowQualityLighting 0\n            -maximumNumHardwareLights 1\n            -occlusionCulling 0\n            -shadingModel 0\n            -useBaseRenderer 0\n            -useReducedRenderer 0\n            -smallObjectCulling 0\n            -smallObjectThreshold -1 \n            -interactiveDisableShadows 0\n            -interactiveBackFaceCull 0\n            -sortTransparent 1\n            -controllers 1\n            -nurbsCurves 1\n            -nurbsSurfaces 1\n            -polymeshes 1\n            -subdivSurfaces 1\n            -planes 1\n            -lights 1\n            -cameras 1\n            -controlVertices 1\n            -hulls 1\n            -grid 1\n            -imagePlane 1\n            -joints 1\n            -ikHandles 1\n            -deformers 1\n            -dynamics 1\n            -particleInstancers 1\n            -fluids 1\n            -hairSystems 1\n            -follicles 1\n            -nCloths 1\n"
		+ "            -nParticles 1\n            -nRigids 1\n            -dynamicConstraints 1\n            -locators 1\n            -manipulators 1\n            -pluginShapes 1\n            -dimensions 1\n            -handles 1\n            -pivots 1\n            -textures 1\n            -strokes 1\n            -motionTrails 1\n            -clipGhosts 1\n            -bluePencil 1\n            -greasePencils 0\n            -excludeObjectPreset \"All\" \n            -shadows 0\n            -captureSequenceNumber -1\n            -width 1\n            -height 1\n            -sceneRenderFilter 0\n            $editorName;\n        modelEditor -e -viewSelected 0 $editorName;\n        modelEditor -e \n            -pluginObjects \"gpuCacheDisplayFilter\" 1 \n            -pluginObjects \"mayaUsdProxyShapeBaseDisplayFilter\" 1 \n            $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"modelPanel\" (localizedPanelLabel(\"Persp View\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n"
		+ "\t\tmodelPanel -edit -l (localizedPanelLabel(\"Persp View\")) -mbv $menusOkayInPanels  $panelName;\n\t\t$editorName = $panelName;\n        modelEditor -e \n            -camera \"|persp\" \n            -useInteractiveMode 0\n            -displayLights \"default\" \n            -displayAppearance \"smoothShaded\" \n            -activeOnly 0\n            -ignorePanZoom 0\n            -wireframeOnShaded 0\n            -headsUpDisplay 1\n            -holdOuts 1\n            -selectionHiliteDisplay 1\n            -useDefaultMaterial 0\n            -bufferMode \"double\" \n            -twoSidedLighting 0\n            -backfaceCulling 0\n            -xray 0\n            -jointXray 0\n            -activeComponentsXray 0\n            -displayTextures 0\n            -smoothWireframe 0\n            -lineWidth 1\n            -textureAnisotropic 0\n            -textureHilight 1\n            -textureSampling 2\n            -textureDisplay \"modulate\" \n            -textureMaxSize 32768\n            -fogging 0\n            -fogSource \"fragment\" \n            -fogMode \"linear\" \n"
		+ "            -fogStart 0\n            -fogEnd 100\n            -fogDensity 0.1\n            -fogColor 0.5 0.5 0.5 1 \n            -depthOfFieldPreview 1\n            -maxConstantTransparency 1\n            -rendererName \"vp2Renderer\" \n            -objectFilterShowInHUD 1\n            -isFiltered 0\n            -colorResolution 256 256 \n            -bumpResolution 512 512 \n            -textureCompression 0\n            -transparencyAlgorithm \"frontAndBackCull\" \n            -transpInShadows 0\n            -cullingOverride \"none\" \n            -lowQualityLighting 0\n            -maximumNumHardwareLights 1\n            -occlusionCulling 0\n            -shadingModel 0\n            -useBaseRenderer 0\n            -useReducedRenderer 0\n            -smallObjectCulling 0\n            -smallObjectThreshold -1 \n            -interactiveDisableShadows 0\n            -interactiveBackFaceCull 0\n            -sortTransparent 1\n            -controllers 1\n            -nurbsCurves 1\n            -nurbsSurfaces 1\n            -polymeshes 1\n            -subdivSurfaces 1\n"
		+ "            -planes 1\n            -lights 1\n            -cameras 1\n            -controlVertices 1\n            -hulls 1\n            -grid 1\n            -imagePlane 1\n            -joints 1\n            -ikHandles 1\n            -deformers 1\n            -dynamics 1\n            -particleInstancers 1\n            -fluids 1\n            -hairSystems 1\n            -follicles 1\n            -nCloths 1\n            -nParticles 1\n            -nRigids 1\n            -dynamicConstraints 1\n            -locators 1\n            -manipulators 1\n            -pluginShapes 1\n            -dimensions 1\n            -handles 1\n            -pivots 1\n            -textures 1\n            -strokes 1\n            -motionTrails 1\n            -clipGhosts 1\n            -bluePencil 1\n            -greasePencils 0\n            -excludeObjectPreset \"All\" \n            -shadows 0\n            -captureSequenceNumber -1\n            -width 2779\n            -height 1473\n            -sceneRenderFilter 0\n            $editorName;\n        modelEditor -e -viewSelected 0 $editorName;\n"
		+ "        modelEditor -e \n            -pluginObjects \"gpuCacheDisplayFilter\" 1 \n            -pluginObjects \"mayaUsdProxyShapeBaseDisplayFilter\" 1 \n            $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"outlinerPanel\" (localizedPanelLabel(\"ToggledOutliner\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\toutlinerPanel -edit -l (localizedPanelLabel(\"ToggledOutliner\")) -mbv $menusOkayInPanels  $panelName;\n\t\t$editorName = $panelName;\n        outlinerEditor -e \n            -showShapes 0\n            -showAssignedMaterials 0\n            -showTimeEditor 1\n            -showReferenceNodes 1\n            -showReferenceMembers 1\n            -showAttributes 0\n            -showConnected 0\n            -showAnimCurvesOnly 0\n            -showMuteInfo 0\n            -organizeByLayer 1\n            -organizeByClip 1\n            -showAnimLayerWeight 1\n            -autoExpandLayers 1\n            -autoExpand 0\n            -showDagOnly 1\n"
		+ "            -showAssets 1\n            -showContainedOnly 1\n            -showPublishedAsConnected 0\n            -showParentContainers 0\n            -showContainerContents 1\n            -ignoreDagHierarchy 0\n            -expandConnections 0\n            -showUpstreamCurves 1\n            -showUnitlessCurves 1\n            -showCompounds 1\n            -showLeafs 1\n            -showNumericAttrsOnly 0\n            -highlightActive 1\n            -autoSelectNewObjects 0\n            -doNotSelectNewObjects 0\n            -dropIsParent 1\n            -transmitFilters 0\n            -setFilter \"defaultSetFilter\" \n            -showSetMembers 1\n            -allowMultiSelection 1\n            -alwaysToggleSelect 0\n            -directSelect 0\n            -isSet 0\n            -isSetMember 0\n            -showUfeItems 1\n            -displayMode \"DAG\" \n            -expandObjects 0\n            -setsIgnoreFilters 1\n            -containersIgnoreFilters 0\n            -editAttrName 0\n            -showAttrValues 0\n            -highlightSecondary 0\n"
		+ "            -showUVAttrsOnly 0\n            -showTextureNodesOnly 0\n            -attrAlphaOrder \"default\" \n            -animLayerFilterOptions \"allAffecting\" \n            -sortOrder \"none\" \n            -longNames 0\n            -niceNames 1\n            -showNamespace 1\n            -showPinIcons 0\n            -mapMotionTrails 0\n            -ignoreHiddenAttribute 0\n            -ignoreOutlinerColor 0\n            -renderFilterVisible 0\n            -renderFilterIndex 0\n            -selectionOrder \"chronological\" \n            -expandAttribute 0\n            $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"outlinerPanel\" (localizedPanelLabel(\"Outliner\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\toutlinerPanel -edit -l (localizedPanelLabel(\"Outliner\")) -mbv $menusOkayInPanels  $panelName;\n\t\t$editorName = $panelName;\n        outlinerEditor -e \n            -showShapes 0\n            -showAssignedMaterials 0\n            -showTimeEditor 1\n"
		+ "            -showReferenceNodes 0\n            -showReferenceMembers 0\n            -showAttributes 0\n            -showConnected 0\n            -showAnimCurvesOnly 0\n            -showMuteInfo 0\n            -organizeByLayer 1\n            -organizeByClip 1\n            -showAnimLayerWeight 1\n            -autoExpandLayers 1\n            -autoExpand 0\n            -showDagOnly 1\n            -showAssets 1\n            -showContainedOnly 1\n            -showPublishedAsConnected 0\n            -showParentContainers 0\n            -showContainerContents 1\n            -ignoreDagHierarchy 0\n            -expandConnections 0\n            -showUpstreamCurves 1\n            -showUnitlessCurves 1\n            -showCompounds 1\n            -showLeafs 1\n            -showNumericAttrsOnly 0\n            -highlightActive 1\n            -autoSelectNewObjects 0\n            -doNotSelectNewObjects 0\n            -dropIsParent 1\n            -transmitFilters 0\n            -setFilter \"defaultSetFilter\" \n            -showSetMembers 1\n            -allowMultiSelection 1\n"
		+ "            -alwaysToggleSelect 0\n            -directSelect 0\n            -showUfeItems 1\n            -displayMode \"DAG\" \n            -expandObjects 0\n            -setsIgnoreFilters 1\n            -containersIgnoreFilters 0\n            -editAttrName 0\n            -showAttrValues 0\n            -highlightSecondary 0\n            -showUVAttrsOnly 0\n            -showTextureNodesOnly 0\n            -attrAlphaOrder \"default\" \n            -animLayerFilterOptions \"allAffecting\" \n            -sortOrder \"none\" \n            -longNames 0\n            -niceNames 1\n            -showNamespace 1\n            -showPinIcons 0\n            -mapMotionTrails 0\n            -ignoreHiddenAttribute 0\n            -ignoreOutlinerColor 0\n            -renderFilterVisible 0\n            $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"graphEditor\" (localizedPanelLabel(\"Graph Editor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Graph Editor\")) -mbv $menusOkayInPanels  $panelName;\n"
		+ "\n\t\t\t$editorName = ($panelName+\"OutlineEd\");\n            outlinerEditor -e \n                -showShapes 1\n                -showAssignedMaterials 0\n                -showTimeEditor 1\n                -showReferenceNodes 0\n                -showReferenceMembers 0\n                -showAttributes 1\n                -showConnected 1\n                -showAnimCurvesOnly 1\n                -showMuteInfo 0\n                -organizeByLayer 1\n                -organizeByClip 1\n                -showAnimLayerWeight 1\n                -autoExpandLayers 1\n                -autoExpand 1\n                -showDagOnly 0\n                -showAssets 1\n                -showContainedOnly 0\n                -showPublishedAsConnected 0\n                -showParentContainers 0\n                -showContainerContents 0\n                -ignoreDagHierarchy 0\n                -expandConnections 1\n                -showUpstreamCurves 1\n                -showUnitlessCurves 1\n                -showCompounds 0\n                -showLeafs 1\n                -showNumericAttrsOnly 1\n"
		+ "                -highlightActive 0\n                -autoSelectNewObjects 1\n                -doNotSelectNewObjects 0\n                -dropIsParent 1\n                -transmitFilters 1\n                -setFilter \"0\" \n                -showSetMembers 0\n                -allowMultiSelection 1\n                -alwaysToggleSelect 0\n                -directSelect 0\n                -showUfeItems 1\n                -displayMode \"DAG\" \n                -expandObjects 0\n                -setsIgnoreFilters 1\n                -containersIgnoreFilters 0\n                -editAttrName 0\n                -showAttrValues 0\n                -highlightSecondary 0\n                -showUVAttrsOnly 0\n                -showTextureNodesOnly 0\n                -attrAlphaOrder \"default\" \n                -animLayerFilterOptions \"allAffecting\" \n                -sortOrder \"none\" \n                -longNames 0\n                -niceNames 1\n                -showNamespace 1\n                -showPinIcons 1\n                -mapMotionTrails 1\n                -ignoreHiddenAttribute 0\n"
		+ "                -ignoreOutlinerColor 0\n                -renderFilterVisible 0\n                $editorName;\n\n\t\t\t$editorName = ($panelName+\"GraphEd\");\n            animCurveEditor -e \n                -displayValues 0\n                -snapTime \"integer\" \n                -snapValue \"none\" \n                -showPlayRangeShades \"on\" \n                -lockPlayRangeShades \"off\" \n                -smoothness \"fine\" \n                -resultSamples 1\n                -resultScreenSamples 0\n                -resultUpdate \"delayed\" \n                -showUpstreamCurves 1\n                -showRowButtons 1\n                -tangentScale 1\n                -tangentLineThickness 1\n                -keyMinScale 1\n                -stackedCurvesMin -1\n                -stackedCurvesMax 1\n                -stackedCurvesSpace 0.2\n                -preSelectionHighlight 0\n                -limitToSelectedCurves 0\n                -constrainDrag 0\n                -valueLinesToggle 0\n                -outliner \"graphEditor1OutlineEd\" \n                -highlightAffectedCurves 0\n"
		+ "                $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"dopeSheetPanel\" (localizedPanelLabel(\"Dope Sheet\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Dope Sheet\")) -mbv $menusOkayInPanels  $panelName;\n\n\t\t\t$editorName = ($panelName+\"OutlineEd\");\n            outlinerEditor -e \n                -showShapes 1\n                -showAssignedMaterials 0\n                -showTimeEditor 1\n                -showReferenceNodes 0\n                -showReferenceMembers 0\n                -showAttributes 1\n                -showConnected 1\n                -showAnimCurvesOnly 1\n                -showMuteInfo 0\n                -organizeByLayer 1\n                -organizeByClip 1\n                -showAnimLayerWeight 1\n                -autoExpandLayers 1\n                -autoExpand 0\n                -showDagOnly 0\n                -showAssets 1\n                -showContainedOnly 0\n"
		+ "                -showPublishedAsConnected 0\n                -showParentContainers 0\n                -showContainerContents 0\n                -ignoreDagHierarchy 0\n                -expandConnections 1\n                -showUpstreamCurves 1\n                -showUnitlessCurves 0\n                -showCompounds 0\n                -showLeafs 1\n                -showNumericAttrsOnly 1\n                -highlightActive 0\n                -autoSelectNewObjects 0\n                -doNotSelectNewObjects 1\n                -dropIsParent 1\n                -transmitFilters 0\n                -setFilter \"0\" \n                -showSetMembers 1\n                -allowMultiSelection 1\n                -alwaysToggleSelect 0\n                -directSelect 0\n                -showUfeItems 1\n                -displayMode \"DAG\" \n                -expandObjects 0\n                -setsIgnoreFilters 1\n                -containersIgnoreFilters 0\n                -editAttrName 0\n                -showAttrValues 0\n                -highlightSecondary 0\n                -showUVAttrsOnly 0\n"
		+ "                -showTextureNodesOnly 0\n                -attrAlphaOrder \"default\" \n                -animLayerFilterOptions \"allAffecting\" \n                -sortOrder \"none\" \n                -longNames 0\n                -niceNames 1\n                -showNamespace 1\n                -showPinIcons 0\n                -mapMotionTrails 1\n                -ignoreHiddenAttribute 0\n                -ignoreOutlinerColor 0\n                -renderFilterVisible 0\n                $editorName;\n\n\t\t\t$editorName = ($panelName+\"DopeSheetEd\");\n            dopeSheetEditor -e \n                -displayValues 0\n                -snapTime \"none\" \n                -snapValue \"none\" \n                -outliner \"dopeSheetPanel1OutlineEd\" \n                -hierarchyBelow 0\n                -selectionWindow 0 0 0 0 \n                $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"timeEditorPanel\" (localizedPanelLabel(\"Time Editor\")) `;\n\tif (\"\" != $panelName) {\n"
		+ "\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Time Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"clipEditorPanel\" (localizedPanelLabel(\"Trax Editor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Trax Editor\")) -mbv $menusOkayInPanels  $panelName;\n\n\t\t\t$editorName = clipEditorNameFromPanel($panelName);\n            clipEditor -e \n                -displayValues 0\n                -snapTime \"none\" \n                -snapValue \"none\" \n                -initialized 0\n                -manageSequencer 0 \n                $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"sequenceEditorPanel\" (localizedPanelLabel(\"Sequencer\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Sequencer\")) -mbv $menusOkayInPanels  $panelName;\n"
		+ "\n\t\t\t$editorName = sequenceEditorNameFromPanel($panelName);\n            cameraSequencer -e \n                -displayValues 0\n                -snapTime \"none\" \n                -snapValue \"none\" \n                -initialized 0\n                -showThumbnail 1\n                $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"hyperGraphPanel\" (localizedPanelLabel(\"Hypergraph Hierarchy\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Hypergraph Hierarchy\")) -mbv $menusOkayInPanels  $panelName;\n\n\t\t\t$editorName = ($panelName+\"HyperGraphEd\");\n            hyperGraph -e \n                -graphLayoutStyle \"hierarchicalLayout\" \n                -orientation \"horiz\" \n                -mergeConnections 0\n                -zoom 1\n                -animateTransition 0\n                -showRelationships 1\n                -showShapes 0\n                -showDeformers 0\n                -showExpressions 0\n"
		+ "                -showConstraints 0\n                -showConnectionFromSelected 0\n                -showConnectionToSelected 0\n                -showConstraintLabels 0\n                -showUnderworld 0\n                -showInvisible 0\n                -showNamespace 1\n                -transitionFrames 1\n                -opaqueContainers 0\n                -freeform 0\n                -imagePosition 0 0 \n                -imageScale 1\n                -imageEnabled 0\n                -graphType \"DAG\" \n                -heatMapDisplay 0\n                -updateSelection 1\n                -updateNodeAdded 1\n                -useDrawOverrideColor 0\n                -limitGraphTraversal -1\n                -range 0 0 \n                -iconSize \"smallIcons\" \n                -showCachedConnections 0\n                $editorName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"hyperShadePanel\" (localizedPanelLabel(\"Hypershade\")) `;\n\tif (\"\" != $panelName) {\n"
		+ "\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Hypershade\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"visorPanel\" (localizedPanelLabel(\"Visor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Visor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"nodeEditorPanel\" (localizedPanelLabel(\"Node Editor\")) `;\n\tif ($nodeEditorPanelVisible || $nodeEditorWorkspaceControlOpen) {\n\t\tif (\"\" == $panelName) {\n\t\t\tif ($useSceneConfig) {\n\t\t\t\t$panelName = `scriptedPanel -unParent  -type \"nodeEditorPanel\" -l (localizedPanelLabel(\"Node Editor\")) -mbv $menusOkayInPanels `;\n\n\t\t\t$editorName = ($panelName+\"NodeEditorEd\");\n            nodeEditor -e \n                -allAttributes 0\n                -allNodes 0\n"
		+ "                -autoSizeNodes 1\n                -consistentNameSize 1\n                -createNodeCommand \"nodeEdCreateNodeCommand\" \n                -connectNodeOnCreation 0\n                -connectOnDrop 0\n                -copyConnectionsOnPaste 0\n                -connectionStyle \"bezier\" \n                -defaultPinnedState 0\n                -additiveGraphingMode 0\n                -connectedGraphingMode 1\n                -settingsChangedCallback \"nodeEdSyncControls\" \n                -traversalDepthLimit -1\n                -keyPressCommand \"nodeEdKeyPressCommand\" \n                -nodeTitleMode \"name\" \n                -gridSnap 0\n                -gridVisibility 1\n                -crosshairOnEdgeDragging 0\n                -popupMenuScript \"nodeEdBuildPanelMenus\" \n                -showNamespace 1\n                -showShapes 1\n                -showSGShapes 0\n                -showTransforms 1\n                -useAssets 1\n                -syncedSelection 1\n                -extendToShapes 1\n                -showUnitConversions 0\n"
		+ "                -editorMode \"default\" \n                -hasWatchpoint 0\n                $editorName;\n\t\t\t}\n\t\t} else {\n\t\t\t$label = `panel -q -label $panelName`;\n\t\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Node Editor\")) -mbv $menusOkayInPanels  $panelName;\n\n\t\t\t$editorName = ($panelName+\"NodeEditorEd\");\n            nodeEditor -e \n                -allAttributes 0\n                -allNodes 0\n                -autoSizeNodes 1\n                -consistentNameSize 1\n                -createNodeCommand \"nodeEdCreateNodeCommand\" \n                -connectNodeOnCreation 0\n                -connectOnDrop 0\n                -copyConnectionsOnPaste 0\n                -connectionStyle \"bezier\" \n                -defaultPinnedState 0\n                -additiveGraphingMode 0\n                -connectedGraphingMode 1\n                -settingsChangedCallback \"nodeEdSyncControls\" \n                -traversalDepthLimit -1\n                -keyPressCommand \"nodeEdKeyPressCommand\" \n                -nodeTitleMode \"name\" \n                -gridSnap 0\n"
		+ "                -gridVisibility 1\n                -crosshairOnEdgeDragging 0\n                -popupMenuScript \"nodeEdBuildPanelMenus\" \n                -showNamespace 1\n                -showShapes 1\n                -showSGShapes 0\n                -showTransforms 1\n                -useAssets 1\n                -syncedSelection 1\n                -extendToShapes 1\n                -showUnitConversions 0\n                -editorMode \"default\" \n                -hasWatchpoint 0\n                $editorName;\n\t\t\tif (!$useSceneConfig) {\n\t\t\t\tpanel -e -l $label $panelName;\n\t\t\t}\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"createNodePanel\" (localizedPanelLabel(\"Create Node\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Create Node\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"polyTexturePlacementPanel\" (localizedPanelLabel(\"UV Editor\")) `;\n"
		+ "\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"UV Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"renderWindowPanel\" (localizedPanelLabel(\"Render View\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Render View\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"shapePanel\" (localizedPanelLabel(\"Shape Editor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tshapePanel -edit -l (localizedPanelLabel(\"Shape Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextPanel \"posePanel\" (localizedPanelLabel(\"Pose Editor\")) `;\n\tif (\"\" != $panelName) {\n"
		+ "\t\t$label = `panel -q -label $panelName`;\n\t\tposePanel -edit -l (localizedPanelLabel(\"Pose Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"dynRelEdPanel\" (localizedPanelLabel(\"Dynamic Relationships\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Dynamic Relationships\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"relationshipPanel\" (localizedPanelLabel(\"Relationship Editor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Relationship Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"referenceEditorPanel\" (localizedPanelLabel(\"Reference Editor\")) `;\n"
		+ "\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Reference Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"dynPaintScriptedPanelType\" (localizedPanelLabel(\"Paint Effects\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Paint Effects\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"scriptEditorPanel\" (localizedPanelLabel(\"Script Editor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Script Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"profilerPanel\" (localizedPanelLabel(\"Profiler Tool\")) `;\n"
		+ "\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Profiler Tool\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"motionMakerEditorPanel\" (localizedPanelLabel(\"MotionMaker Editor\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"MotionMaker Editor\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\t$panelName = `sceneUIReplacement -getNextScriptedPanel \"contentBrowserPanel\" (localizedPanelLabel(\"Content Browser\")) `;\n\tif (\"\" != $panelName) {\n\t\t$label = `panel -q -label $panelName`;\n\t\tscriptedPanel -edit -l (localizedPanelLabel(\"Content Browser\")) -mbv $menusOkayInPanels  $panelName;\n\t\tif (!$useSceneConfig) {\n\t\t\tpanel -e -l $label $panelName;\n\t\t}\n\t}\n\n\n\tif ($useSceneConfig) {\n        string $configName = `getPanel -cwl (localizedPanelLabel(\"Current Layout\"))`;\n"
		+ "        if (\"\" != $configName) {\n\t\t\tpanelConfiguration -edit -label (localizedPanelLabel(\"Current Layout\")) \n\t\t\t\t-userCreated false\n\t\t\t\t-defaultImage \"\"\n\t\t\t\t-image \"\"\n\t\t\t\t-sc false\n\t\t\t\t-configString \"global string $gMainPane; paneLayout -e -cn \\\"single\\\" -ps 1 100 100 $gMainPane;\"\n\t\t\t\t-removeAllPanels\n\t\t\t\t-ap false\n\t\t\t\t\t(localizedPanelLabel(\"Persp View\")) \n\t\t\t\t\t\"modelPanel\"\n"
		+ "\t\t\t\t\t\"$panelName = `modelPanel -unParent -l (localizedPanelLabel(\\\"Persp View\\\")) -mbv $menusOkayInPanels `;\\n$editorName = $panelName;\\nmodelEditor -e \\n    -cam `findStartUpCamera persp` \\n    -useInteractiveMode 0\\n    -displayLights \\\"default\\\" \\n    -displayAppearance \\\"smoothShaded\\\" \\n    -activeOnly 0\\n    -ignorePanZoom 0\\n    -wireframeOnShaded 0\\n    -headsUpDisplay 1\\n    -holdOuts 1\\n    -selectionHiliteDisplay 1\\n    -useDefaultMaterial 0\\n    -bufferMode \\\"double\\\" \\n    -twoSidedLighting 0\\n    -backfaceCulling 0\\n    -xray 0\\n    -jointXray 0\\n    -activeComponentsXray 0\\n    -displayTextures 0\\n    -smoothWireframe 0\\n    -lineWidth 1\\n    -textureAnisotropic 0\\n    -textureHilight 1\\n    -textureSampling 2\\n    -textureDisplay \\\"modulate\\\" \\n    -textureMaxSize 32768\\n    -fogging 0\\n    -fogSource \\\"fragment\\\" \\n    -fogMode \\\"linear\\\" \\n    -fogStart 0\\n    -fogEnd 100\\n    -fogDensity 0.1\\n    -fogColor 0.5 0.5 0.5 1 \\n    -depthOfFieldPreview 1\\n    -maxConstantTransparency 1\\n    -rendererName \\\"vp2Renderer\\\" \\n    -objectFilterShowInHUD 1\\n    -isFiltered 0\\n    -colorResolution 256 256 \\n    -bumpResolution 512 512 \\n    -textureCompression 0\\n    -transparencyAlgorithm \\\"frontAndBackCull\\\" \\n    -transpInShadows 0\\n    -cullingOverride \\\"none\\\" \\n    -lowQualityLighting 0\\n    -maximumNumHardwareLights 1\\n    -occlusionCulling 0\\n    -shadingModel 0\\n    -useBaseRenderer 0\\n    -useReducedRenderer 0\\n    -smallObjectCulling 0\\n    -smallObjectThreshold -1 \\n    -interactiveDisableShadows 0\\n    -interactiveBackFaceCull 0\\n    -sortTransparent 1\\n    -controllers 1\\n    -nurbsCurves 1\\n    -nurbsSurfaces 1\\n    -polymeshes 1\\n    -subdivSurfaces 1\\n    -planes 1\\n    -lights 1\\n    -cameras 1\\n    -controlVertices 1\\n    -hulls 1\\n    -grid 1\\n    -imagePlane 1\\n    -joints 1\\n    -ikHandles 1\\n    -deformers 1\\n    -dynamics 1\\n    -particleInstancers 1\\n    -fluids 1\\n    -hairSystems 1\\n    -follicles 1\\n    -nCloths 1\\n    -nParticles 1\\n    -nRigids 1\\n    -dynamicConstraints 1\\n    -locators 1\\n    -manipulators 1\\n    -pluginShapes 1\\n    -dimensions 1\\n    -handles 1\\n    -pivots 1\\n    -textures 1\\n    -strokes 1\\n    -motionTrails 1\\n    -clipGhosts 1\\n    -bluePencil 1\\n    -greasePencils 0\\n    -excludeObjectPreset \\\"All\\\" \\n    -shadows 0\\n    -captureSequenceNumber -1\\n    -width 2779\\n    -height 1473\\n    -sceneRenderFilter 0\\n    $editorName;\\nmodelEditor -e -viewSelected 0 $editorName;\\nmodelEditor -e \\n    -pluginObjects \\\"gpuCacheDisplayFilter\\\" 1 \\n    -pluginObjects \\\"mayaUsdProxyShapeBaseDisplayFilter\\\" 1 \\n    $editorName\"\n"
		+ "\t\t\t\t\t\"modelPanel -edit -l (localizedPanelLabel(\\\"Persp View\\\")) -mbv $menusOkayInPanels  $panelName;\\n$editorName = $panelName;\\nmodelEditor -e \\n    -cam `findStartUpCamera persp` \\n    -useInteractiveMode 0\\n    -displayLights \\\"default\\\" \\n    -displayAppearance \\\"smoothShaded\\\" \\n    -activeOnly 0\\n    -ignorePanZoom 0\\n    -wireframeOnShaded 0\\n    -headsUpDisplay 1\\n    -holdOuts 1\\n    -selectionHiliteDisplay 1\\n    -useDefaultMaterial 0\\n    -bufferMode \\\"double\\\" \\n    -twoSidedLighting 0\\n    -backfaceCulling 0\\n    -xray 0\\n    -jointXray 0\\n    -activeComponentsXray 0\\n    -displayTextures 0\\n    -smoothWireframe 0\\n    -lineWidth 1\\n    -textureAnisotropic 0\\n    -textureHilight 1\\n    -textureSampling 2\\n    -textureDisplay \\\"modulate\\\" \\n    -textureMaxSize 32768\\n    -fogging 0\\n    -fogSource \\\"fragment\\\" \\n    -fogMode \\\"linear\\\" \\n    -fogStart 0\\n    -fogEnd 100\\n    -fogDensity 0.1\\n    -fogColor 0.5 0.5 0.5 1 \\n    -depthOfFieldPreview 1\\n    -maxConstantTransparency 1\\n    -rendererName \\\"vp2Renderer\\\" \\n    -objectFilterShowInHUD 1\\n    -isFiltered 0\\n    -colorResolution 256 256 \\n    -bumpResolution 512 512 \\n    -textureCompression 0\\n    -transparencyAlgorithm \\\"frontAndBackCull\\\" \\n    -transpInShadows 0\\n    -cullingOverride \\\"none\\\" \\n    -lowQualityLighting 0\\n    -maximumNumHardwareLights 1\\n    -occlusionCulling 0\\n    -shadingModel 0\\n    -useBaseRenderer 0\\n    -useReducedRenderer 0\\n    -smallObjectCulling 0\\n    -smallObjectThreshold -1 \\n    -interactiveDisableShadows 0\\n    -interactiveBackFaceCull 0\\n    -sortTransparent 1\\n    -controllers 1\\n    -nurbsCurves 1\\n    -nurbsSurfaces 1\\n    -polymeshes 1\\n    -subdivSurfaces 1\\n    -planes 1\\n    -lights 1\\n    -cameras 1\\n    -controlVertices 1\\n    -hulls 1\\n    -grid 1\\n    -imagePlane 1\\n    -joints 1\\n    -ikHandles 1\\n    -deformers 1\\n    -dynamics 1\\n    -particleInstancers 1\\n    -fluids 1\\n    -hairSystems 1\\n    -follicles 1\\n    -nCloths 1\\n    -nParticles 1\\n    -nRigids 1\\n    -dynamicConstraints 1\\n    -locators 1\\n    -manipulators 1\\n    -pluginShapes 1\\n    -dimensions 1\\n    -handles 1\\n    -pivots 1\\n    -textures 1\\n    -strokes 1\\n    -motionTrails 1\\n    -clipGhosts 1\\n    -bluePencil 1\\n    -greasePencils 0\\n    -excludeObjectPreset \\\"All\\\" \\n    -shadows 0\\n    -captureSequenceNumber -1\\n    -width 2779\\n    -height 1473\\n    -sceneRenderFilter 0\\n    $editorName;\\nmodelEditor -e -viewSelected 0 $editorName;\\nmodelEditor -e \\n    -pluginObjects \\\"gpuCacheDisplayFilter\\\" 1 \\n    -pluginObjects \\\"mayaUsdProxyShapeBaseDisplayFilter\\\" 1 \\n    $editorName\"\n"
		+ "\t\t\t\t$configName;\n\n            setNamedPanelLayout (localizedPanelLabel(\"Current Layout\"));\n        }\n\n        panelHistory -e -clear mainPanelHistory;\n        sceneUIReplacement -clear;\n\t}\n\n\ngrid -spacing 5 -size 12 -divisions 5 -displayAxes yes -displayGridLines yes -displayDivisionLines yes -displayPerspectiveLabels no -displayOrthographicLabels no -displayAxesBold yes -perspectiveLabelPosition axis -orthographicLabelPosition edge;\nviewManip -drawCompass 0 -compassAngle 0 -frontParameters \"\" -homeParameters \"\" -selectionLockParameters \"\";\n}\n");
	setAttr ".st" 3;
createNode script -n "sceneConfigurationScriptNode";
	rename -uid "926D1444-409B-7BBF-9302-289F0C3B242B";
	setAttr ".b" -type "string" "playbackOptions -min 1 -max 120 -ast 1 -aet 200 ";
	setAttr ".st" 6;
select -ne :time1;
	setAttr ".o" 1;
	setAttr ".unw" 1;
select -ne :hardwareRenderingGlobals;
	setAttr ".otfna" -type "stringArray" 22 "NURBS Curves" "NURBS Surfaces" "Polygons" "Subdiv Surface" "Particles" "Particle Instance" "Fluids" "Strokes" "Image Planes" "UI" "Lights" "Cameras" "Locators" "Joints" "IK Handles" "Deformers" "Motion Trails" "Components" "Hair Systems" "Follicles" "Misc. UI" "Ornaments"  ;
	setAttr ".otfva" -type "Int32Array" 22 0 1 1 1 1 1
		 1 1 1 0 0 0 0 0 0 0 0 0
		 0 0 0 0 ;
	setAttr ".fprt" yes;
	setAttr ".rtfm" 1;
select -ne :renderPartition;
	setAttr -s 11 ".st";
select -ne :renderGlobalsList1;
select -ne :defaultShaderList1;
	setAttr -s 15 ".s";
select -ne :postProcessList1;
	setAttr -s 2 ".p";
select -ne :defaultRenderingList1;
select -ne :lightList1;
	setAttr -s 3 ".l";
select -ne :standardSurface1;
	setAttr ".bc" -type "float3" 0.40000001 0.40000001 0.40000001 ;
	setAttr ".sr" 0.5;
select -ne :openPBR_shader1;
	setAttr ".bc" -type "float3" 0.40000001 0.40000001 0.40000001 ;
	setAttr ".sr" 0.5;
select -ne :initialShadingGroup;
	setAttr ".ro" yes;
select -ne :initialParticleSE;
	setAttr ".ro" yes;
select -ne :defaultRenderGlobals;
	addAttr -ci true -h true -sn "dss" -ln "defaultSurfaceShader" -dt "string";
	setAttr ".ren" -type "string" "arnold";
	setAttr ".ifp" -type "string" "mayaMcpRender_fdb129cf_0_three_quarter";
	setAttr ".dss" -type "string" "openPBR_shader1";
select -ne :defaultResolution;
	setAttr ".pa" 1;
select -ne :defaultLightSet;
	setAttr -s 3 ".dsm";
select -ne :defaultColorMgtGlobals;
	setAttr ".cfe" yes;
	setAttr ".cfp" -type "string" "<MAYA_RESOURCES>/OCIO-configs/Maya2022-default/config.ocio";
	setAttr ".vtn" -type "string" "ACES 1.0 SDR-video (sRGB)";
	setAttr ".vn" -type "string" "ACES 1.0 SDR-video";
	setAttr ".dn" -type "string" "sRGB";
	setAttr ".wsn" -type "string" "ACEScg";
	setAttr ".otn" -type "string" "ACES 1.0 SDR-video (sRGB)";
	setAttr ".potn" -type "string" "ACES 1.0 SDR-video (sRGB)";
select -ne :hardwareRenderGlobals;
	setAttr ".ctrs" 256;
	setAttr ".btrs" 512;
relationship "link" ":lightLinker1" ":initialShadingGroup.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" ":initialParticleSE.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "ground_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "wallBack_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "wallFront_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "wallLeft_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "wallRight_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "limestone_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "bronze_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "shadowStone_matSG.message" ":defaultLightSet.message";
relationship "link" ":lightLinker1" "glow_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" ":initialShadingGroup.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" ":initialParticleSE.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "ground_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "wallBack_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "wallFront_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "wallLeft_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "wallRight_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "limestone_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "bronze_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "shadowStone_matSG.message" ":defaultLightSet.message";
relationship "shadowLink" ":lightLinker1" "glow_matSG.message" ":defaultLightSet.message";
connectAttr "layerManager.dli[0]" "defaultLayer.id";
connectAttr "renderLayerManager.rlmi[0]" "defaultRenderLayer.rlid";
connectAttr "ground_mat.oc" "ground_matSG.ss";
connectAttr "groundShape.iog" "ground_matSG.dsm" -na;
connectAttr "ground_matSG.msg" "materialInfo1.sg";
connectAttr "ground_mat.msg" "materialInfo1.m";
connectAttr "wallBack_mat.oc" "wallBack_matSG.ss";
connectAttr "wallBackShape.iog" "wallBack_matSG.dsm" -na;
connectAttr "wallBack_matSG.msg" "materialInfo2.sg";
connectAttr "wallBack_mat.msg" "materialInfo2.m";
connectAttr "wallFront_mat.oc" "wallFront_matSG.ss";
connectAttr "wallFrontShape.iog" "wallFront_matSG.dsm" -na;
connectAttr "wallFront_matSG.msg" "materialInfo3.sg";
connectAttr "wallFront_mat.msg" "materialInfo3.m";
connectAttr "wallLeft_mat.oc" "wallLeft_matSG.ss";
connectAttr "wallLeftShape.iog" "wallLeft_matSG.dsm" -na;
connectAttr "wallLeft_matSG.msg" "materialInfo4.sg";
connectAttr "wallLeft_mat.msg" "materialInfo4.m";
connectAttr "wallRight_mat.oc" "wallRight_matSG.ss";
connectAttr "wallRightShape.iog" "wallRight_matSG.dsm" -na;
connectAttr "wallRight_matSG.msg" "materialInfo5.sg";
connectAttr "wallRight_mat.msg" "materialInfo5.m";
connectAttr "limestone_mat.oc" "limestone_matSG.ss";
connectAttr "stylobateShape.iog" "limestone_matSG.dsm" -na;
connectAttr "innerFloorShape.iog" "limestone_matSG.dsm" -na;
connectAttr "architraveShape.iog" "limestone_matSG.dsm" -na;
connectAttr "corniceShape.iog" "limestone_matSG.dsm" -na;
connectAttr "domeShape.iog" "limestone_matSG.dsm" -na;
connectAttr "domeShape.ciog.cog[0]" "limestone_matSG.dsm" -na;
connectAttr "columnShape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_1Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_2Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_3Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_4Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_5Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_6Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_7Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_8Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "column_9Shape.iog" "limestone_matSG.dsm" -na;
connectAttr "limestone_matSG.msg" "materialInfo6.sg";
connectAttr "limestone_mat.msg" "materialInfo6.m";
connectAttr "bronze_mat.oc" "bronze_matSG.ss";
connectAttr "finialShape.iog" "bronze_matSG.dsm" -na;
connectAttr "bronze_matSG.msg" "materialInfo7.sg";
connectAttr "bronze_mat.msg" "materialInfo7.m";
connectAttr "shadowStone_mat.oc" "shadowStone_matSG.ss";
connectAttr "altarShape.iog" "shadowStone_matSG.dsm" -na;
connectAttr "step_baseShape.iog" "shadowStone_matSG.dsm" -na;
connectAttr "step_1Shape.iog" "shadowStone_matSG.dsm" -na;
connectAttr "step_2Shape.iog" "shadowStone_matSG.dsm" -na;
connectAttr "shadowStone_matSG.msg" "materialInfo8.sg";
connectAttr "shadowStone_mat.msg" "materialInfo8.m";
connectAttr "glow_mat.oc" "glow_matSG.ss";
connectAttr "gemShape.iog" "glow_matSG.dsm" -na;
connectAttr "glow_matSG.msg" "materialInfo9.sg";
connectAttr "glow_mat.msg" "materialInfo9.m";
connectAttr "ground_matSG.pa" ":renderPartition.st" -na;
connectAttr "wallBack_matSG.pa" ":renderPartition.st" -na;
connectAttr "wallFront_matSG.pa" ":renderPartition.st" -na;
connectAttr "wallLeft_matSG.pa" ":renderPartition.st" -na;
connectAttr "wallRight_matSG.pa" ":renderPartition.st" -na;
connectAttr "limestone_matSG.pa" ":renderPartition.st" -na;
connectAttr "bronze_matSG.pa" ":renderPartition.st" -na;
connectAttr "shadowStone_matSG.pa" ":renderPartition.st" -na;
connectAttr "glow_matSG.pa" ":renderPartition.st" -na;
connectAttr "ground_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "wallBack_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "wallFront_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "wallLeft_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "wallRight_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "limestone_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "bronze_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "shadowStone_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "glow_mat.msg" ":defaultShaderList1.s" -na;
connectAttr "defaultRenderLayer.msg" ":defaultRenderingList1.r" -na;
connectAttr "mcpLight_keyShape.ltd" ":lightList1.l" -na;
connectAttr "mcpLight_fillShape.ltd" ":lightList1.l" -na;
connectAttr "mcpLight_rimShape.ltd" ":lightList1.l" -na;
connectAttr "mcpLight_key.iog" ":defaultLightSet.dsm" -na;
connectAttr "mcpLight_fill.iog" ":defaultLightSet.dsm" -na;
connectAttr "mcpLight_rim.iog" ":defaultLightSet.dsm" -na;
// End of 001_auto_pre_new_scene.ma
