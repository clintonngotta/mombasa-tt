import { createRequire } from "node:module"
import type { Plugin } from "vite"

type Country = { id: number; iso2: string; name: string }
type State = { id: number; countryId: number; name: string; lifecycleStatus: string; administrativeLevel: number }
type City = { n: string; s: number; c: number }

const require = createRequire(import.meta.url)
const DATASET = "@tansuasici/country-state-city/data/"

function buildAssets() {
  const countries: Country[] = require(DATASET + "countries.json")
  const states: State[] = require(DATASET + "states.json")
  const cities: City[] = require(DATASET + "cities.optimized.json")
  const cityNames = new Map<number, Set<string>>()
  for (const city of cities) {
    const names = cityNames.get(city.s) ?? new Set<string>()
    names.add(city.n)
    cityNames.set(city.s, names)
  }
  const order = (left: string, right: string) => left.localeCompare(right, "en")
  const assets = new Map<string, string>()
  assets.set("countries.json", JSON.stringify(
    countries.map(({ iso2, name }) => ({ value: iso2, label: name })).sort((a, b) => order(a.label, b.label)),
  ))
  for (const { id, iso2 } of countries) {
    const regions = states
      .filter((state) => state.countryId === id && state.lifecycleStatus === "current" && state.administrativeLevel === 1)
      .map(({ id: stateId, name }) => ({ name, cities: [...(cityNames.get(stateId) ?? [])].sort(order) }))
      .sort((a, b) => order(a.name, b.name))
    assets.set(`${iso2}.json`, JSON.stringify(regions))
  }
  return assets
}

/** Serve locations locally and ship compact files per country with the production build. */
export function geographyAssets(): Plugin {
  let assets: ReturnType<typeof buildAssets> | undefined
  const getAssets = () => (assets ??= buildAssets())
  return {
    name: "geography-assets",
    configureServer(server) {
      server.middlewares.use("/geography", (request, response, next) => {
        const filename = request.url?.slice(1).split("?")[0] ?? ""
        if (!/^(countries|[A-Z]{2})\.json$/.test(filename)) return next()
        const source = getAssets().get(filename)
        if (source === undefined) return next()
        response.setHeader("Content-Type", "application/json; charset=utf-8")
        response.end(source)
      })
    },
    generateBundle() {
      for (const [filename, source] of getAssets()) {
        this.emitFile({ type: "asset", fileName: `geography/${filename}`, source })
      }
    },
  }
}
