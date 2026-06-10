import { useEffect, useRef } from 'react'
import { loadMaps } from './maps'

const LOCATE_ZOOM = 11 // 📍後縮放層級：11≈一個縣市（數字越大越近）

// 重構後：純呈現。收 places + selected + onSelect，自己不抓資料、不管篩選。
export default function FoodMap({ places, selected, onSelect }) {
  const mapElRef = useRef(null)
  const mapRef = useRef(null)
  const libsRef = useRef(null)
  const markersRef = useRef([])
  const didFitRef = useRef(false)

  // 開圖（一次）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const libs = await loadMaps()
      if (cancelled) return
      libsRef.current = libs
      mapRef.current = new libs.Map(mapElRef.current, {
        center: { lat: 23.7, lng: 121 },
        zoom: 7,
        mapId: import.meta.env.VITE_GOOGLE_MAPS_MAP_ID || 'DEMO_MAP_ID',
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
      })
      drawMarkers()
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // places 變 → 重畫 marker
  useEffect(() => { drawMarkers() }, [places]) // eslint-disable-line react-hooks/exhaustive-deps

  // selected 變 → 地圖平移過去（清單點選 / 骰子也會帶動地圖）
  useEffect(() => {
    if (selected && mapRef.current) {
      mapRef.current.panTo({ lat: selected.lat, lng: selected.lng })
    }
  }, [selected])

  function drawMarkers() {
    const map = mapRef.current
    const libs = libsRef.current
    if (!map || !libs) return
    for (const m of markersRef.current) m.map = null
    markersRef.current = []
    const bounds = new window.google.maps.LatLngBounds()
    for (const pl of places) {
      const pin = new libs.PinElement(
        pl.visited
          ? { background: '#137333', borderColor: '#0d652d', glyphColor: 'white' }
          : { background: '#1f7dd4', borderColor: '#0d47a1', glyphColor: 'white' },
      )
      const marker = new libs.AdvancedMarkerElement({
        map,
        position: { lat: pl.lat, lng: pl.lng },
        title: pl.name || '',
        content: pin.element,
        gmpClickable: true,
      })
      marker.addListener('click', () => onSelect(pl))
      markersRef.current.push(marker)
      bounds.extend({ lat: pl.lat, lng: pl.lng })
    }
    if (!didFitRef.current && places.length) {
      map.fitBounds(bounds)
      didFitRef.current = true
    }
  }

  function locateMe() {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const map = mapRef.current
        const libs = libsRef.current
        if (!map || !libs) return
        const me = { lat: pos.coords.latitude, lng: pos.coords.longitude }
        map.setCenter(me)
        map.setZoom(LOCATE_ZOOM)
        const pin = new libs.PinElement({
          background: '#ea4335', borderColor: '#b31412', glyphColor: 'white', scale: 1.1,
        })
        new libs.AdvancedMarkerElement({ map, position: me, title: '你的位置', content: pin.element })
      },
      () => {},
      { enableHighAccuracy: false, timeout: 6000, maximumAge: 300000 },
    )
  }

  return (
    <div className="map-tab">
      <div ref={mapElRef} className="map-canvas" />
      <div className="fab-col">
        <button className="fab" onClick={locateMe} title="我附近">📍</button>
      </div>
    </div>
  )
}
