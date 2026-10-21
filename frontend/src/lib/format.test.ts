import { describe, expect, it } from 'vitest'
import { cents, decimal, lineTotal, localDateTime, omskToIso } from './format'

describe('receipt arithmetic', () => {
  it('accepts commas and preserves decimal strings', () => {
    expect(decimal(' 129,90 ')).toBe('129.90')
    expect(decimal('0,125', 3, true)).toBe('0.125')
  })
  it.each(['-1', 'NaN', 'Infinity', '1e3', '1.999', '', '99999999999'])(
    'rejects invalid money %s',
    (value) => {
      expect(() => decimal(value)).toThrow()
    },
  )
  it('rejects zero quantity', () => expect(() => decimal('0', 3, true)).toThrow())
  it('adds cents without floating point errors', () => {
    expect(cents('0.10') + cents('0.20')).toBe(30n)
    expect(cents('9999999999.99')).toBe(999999999999n)
  })
  it('calculates weighted goods with half-up rounding', () => {
    expect(lineTotal('0,125', '79,90')).toBe('9.99')
    expect(lineTotal('3', '0.10')).toBe('0.30')
  })
})
describe('Omsk receipt dates', () => {
  it('shows local Omsk time and converts it back to UTC', () => {
    expect(localDateTime('2026-10-21T09:45:00Z')).toBe('2026-10-21T15:45')
    expect(omskToIso('2026-10-21T15:45')).toBe('2026-10-21T09:45:00.000Z')
  })
})
