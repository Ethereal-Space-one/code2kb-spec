package example;

public final class OrderRule {
    public int deliveryFee(int amountInMinorUnits) {
        return amountInMinorUnits >= 10000 ? 0 : 500;
    }
}
