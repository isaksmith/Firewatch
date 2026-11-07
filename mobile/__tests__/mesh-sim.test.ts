import vectors from '../../docs/mobile/codec-vectors.json';
import { SIM_CODES } from '../src/transports/mesh/sim-codes';

it('simulated radio codes match the contract vectors', () => {
  expect(SIM_CODES).toEqual(vectors.vectors.slice(0, 3).map((v) => v.code));
});
