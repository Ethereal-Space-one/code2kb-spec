package example;

public final class OrderRule {
    public int deliveryFee(int amountInMinorUnits) {
        return amountInMinorUnits >= 8000 ? 0 : 500;
    }
}
