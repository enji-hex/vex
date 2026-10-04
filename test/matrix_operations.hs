-- Short Haskell Matrix Operations
import Data.List (transpose)

type Matrix = [[Double]]

-- Matrix multiplication
mul :: Matrix -> Matrix -> Matrix
mul a b = [[sum [x*y | (x,y) <- zip row col] | col <- transpose b] | row <- a]

-- Determinant (2x2 only)
det :: Matrix -> Double
det [[a,b],[c,d]] = a*d - b*c
det _ = error "Only 2x2 matrices supported"

-- Example usage:
-- let m = [[1,2],[3,4]]
-- mul m m  -- Matrix multiplication
-- det m    -- Determinant