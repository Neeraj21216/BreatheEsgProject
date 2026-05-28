# SOURCES.md

## 1. SAP Flat File

### Real-world format researched
- SAP MB51 / ME2N exports from SAP ECC and S/4HANA,
- typical CSV/TSV with headers like `Menge`, `MEINS`, `Werk`, `Maktx`, `LIFNR`, `BUDAT`, `MBLNR`.
- common German locale quirks: semicolon delimiters, comma decimals, German header names.

### What I learned
- SAP units are often coded values like `KG`, `L`, `TO`, `MWH`, `GJ`.
- plant codes are business-specific and must be mapped to real locations.
- material descriptions are noisy, so category detection is heuristic.

### Sample data shape
```
Document Number,Plant,Date,Quantity,Unit,Description,Vendor
4711,DE01,2024-02-10,25,KG,diesel fuel,Supplier A
4712,US10,2024-02-11,5,MWH,electricity,Supplier B
```

### What would break in a real deployment
- unknown SAP unit codes or compound units,
- plant codes that are not present in `PlantSite`,
- exports with non-standard headers or merged multi-row headers,
- multi-currency cost values without currency normalization.

## 2. Utility CSV

### Real-world format researched
- utility portal exports from EU/UK and U.S. electricity providers,
- columns for `Meter ID`, `Period Start`, `Period End`, `Consumption`, `Unit`, `Read Type`, `Site`, `Country`, `Cost`.

### What I learned
- billing periods are often non-calendar-month and can have missing end dates,
- meter IDs may be labelled `MPAN`, `Account Number`, or `Meter Number`.
- estimated reads are important for quality flags.

### Sample data shape
```
Meter ID,Period Start,Period End,Consumption,Unit,Read Type,Site,Country,Cost
12345,2024-01-14,2024-02-13,1234,kWh,Actual,Factory 1,GB,250.00
```

### What would break in a real deployment
- non-electricity utility types such as gas or water,
- tenant-specific unit codes not in the supported map,
- aggregated portfolio rows rather than meter-level detail,
- missing or malformed dates that require richer rules.

## 3. Corporate Travel CSV

### Real-world format researched
- Concur / Navan CSV exports for flights, hotels, ground transport,
- columns such as `Travel Date`, `Expense Type`, `Origin`, `Destination`, `Class`, `Distance`, `Nights`, `Travellers`, `Cost`.

### What I learned
- air distance is often missing and must be inferred from airport codes,
- cabin class values vary widely and should fall back to `unknown`,
- hotel emissions often need a region-based default factor.

### Sample data shape
```
Date,Travel Type,Origin,Destination,Class,Distance (km),Travellers,Cost,Country
2024-02-05,Air,JFK,LHR,Economy,,1,1200.00,US
2024-02-08,Hotel,,London,Hotel,,2,450.00,GB
```

### What would break in a real deployment
- multi-leg journeys encoded in one row,
- origin/destination values that are not IATA codes,
- corporate travel exports that use different column names or nested itinerary fields,
- missing country context for hotel emissions.
