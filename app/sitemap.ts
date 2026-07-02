import { MetadataRoute } from "next";
import { medicines, medicineTypes, bodyParts, getSeriesList } from "@/data/medicines";

const BASE_URL = "https://minnnanoyakuzaishi.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const seriesList = getSeriesList();

  const medicineUrls = medicines.map((m) => ({
    url: `${BASE_URL}/medicine/${m.id}`,
    lastModified: new Date(),
    changeFrequency: "monthly" as const,
    priority: 0.8,
  }));

  const medicineTypeUrls = medicineTypes.map((t) => ({
    url: `${BASE_URL}/search/medicine_type/${t.id}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.7,
  }));

  const bodyPartUrls = bodyParts.map((b) => ({
    url: `${BASE_URL}/search/body_parts/${b.id}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.7,
  }));

  const seriesUrls = seriesList.map((s) => ({
    url: `${BASE_URL}/search/series_name/${encodeURIComponent(s)}`,
    lastModified: new Date(),
    changeFrequency: "monthly" as const,
    priority: 0.6,
  }));

  return [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1.0 },
    { url: `${BASE_URL}/search/medicine_type`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/search/body_parts`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/search/series_name`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.8 },
    ...medicineTypeUrls,
    ...bodyPartUrls,
    ...seriesUrls,
    ...medicineUrls,
  ];
}
