/**
 * Aerial view of the Nashik onion belt — striped cropland parcels.
 * Uses a real photo dropped in at web/public/field.png and served
 * at /field.png. Cropped to the media frame with object-fit: cover.
 */
export default function FieldRaster() {
  return (
    <img
      src="/field.png"
      alt="Sentinel-2 aerial view of the Nashik onion belt"
      loading="eager"
      decoding="async"
    />
  )
}
